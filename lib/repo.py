#!/bin/python3

import os
import zlib
import lzma
import hashlib
import logging
import shutil
import requests
import yaml
import lib.tools as tools
import concurrent.futures
import urllib3
from time import sleep
import glob
import re

# Log only error request
logging.getLogger("urllib3").setLevel(logging.ERROR)

if not os.path.exists('config.yaml'):
    logging.error('Le fichier config.yaml est manquant !')
    exit(1)

config = yaml.safe_load(open('config.yaml', 'r'))

if config['verify_file_mode'] not in ['packages', 'checksum']:
    logging.error('La valeur de verify_file_mode semble incorrect "%s" !' % config['verify_file_mode'])
    exit(1)

# Hide alert ignore SSL certificate
urllib3.disable_warnings()

if config['http_proxy_enable']:
    http = urllib3.ProxyManager(config['http_proxy'], maxsize=config['http_max_request'], cert_reqs='CERT_NONE')
    proxies = { 'http': config['http_proxy'], 'https': config['http_proxy'] }
else:
    http = urllib3.PoolManager(maxsize=config['http_max_request'], cert_reqs='CERT_NONE')
    proxies = {}

class repositoryManager():


    def __init__(self, repo):
        self.url = repo['url']
        self.distributions = [str(x) for x in repo['distributions']]
        self.components = [str(x) for x in repo['components']]
        self.archs = [str(x) for x in repo['archs']]
        self.is_clone = 'clone' in repo
        self.is_override = 'override_path' in repo
        self.ignore_error = 'ignore_error' in repo and repo['ignore_error']

        self.failure = False
        self.error_files = []

        if self.is_clone:
            self.clone = repo['clone']

        if self.is_override:
            self.repo_www = os.path.join(config['www_dir'], repo['override_path'])
            self.repo_tmp = os.path.join(config['tmp_dir'], repo['override_path'])
            self.name = (repo['override_path']).split('/')[0]
        else:
            self.repo_www = os.path.join(config['www_dir'], self.url.split('://')[1])
            self.repo_tmp = os.path.join(config['tmp_dir'], self.url.split('://')[1])
            self.name = (self.url.split('://')[1]).split('/')[0]


    def initialize(self):
        self.logger = logging.getLogger(self.url)

        if os.path.exists(self.repo_www) and os.path.islink(self.repo_www):
            self.logger.error("Error dir is link, remove ...")
            os.remove(self.repo_www)

        # Get all debians and packages for repo
        self.debians_present = []
        self.packages_present = []
        self.files_present = []
        for dirpath, dirs, files in os.walk(self.repo_www):
            for f in files:
                if f.endswith('.deb') or f.endswith('.udeb') or f.endswith('.ddeb'):
                    self.debians_present.append(os.path.join(dirpath, f).replace(self.repo_www + '/', ''))
                elif f.endswith('Packages'):
                    self.packages_present.append(os.path.join(dirpath, f))
                else:
                    self.files_present.append(os.path.join(dirpath, f))


    def apply_repo(self):
        if not self.failure and os.path.exists(self.repo_tmp):
            tools.merge_dir(self.repo_tmp, self.repo_www)


    def cleanup(self):
        if os.path.exists(self.repo_tmp):
            shutil.rmtree(self.repo_tmp)


    def set_failure(self, filepath):
        self.error_files.append(filepath)
        self.logger.error("Erreur durant le process avec le fichier %s !" % filepath)
        self.failure = True
        return False

    def is_checksum(self, filename, checksum):
        filename_path = os.path.join(self.repo_www, filename)
        is_same, sha256 = tools.checksha256(filename_path, checksum)
        return is_same, filename

    def is_size(self, filename, size):
        filename_path = os.path.join(self.repo_www, filename)
        is_same, sha256 = tools.checksize(filename_path, size)
        return is_same, filename

    def get_deb(self, filename, fileinfo, retry=False):

        if self.failure:
            return False

        filename_path = os.path.join(self.repo_tmp, filename)

        idx = self.need_download.index(filename)

        if self.is_clone:
            try:
                os.link(os.path.join(self.clone, filename), filename_path)
                return True
            except:
                self.logger.info('Failure ... download [%s/%s] %s' % (idx + 1, len(need_download), filename))

        deb_url = os.path.join(self.url, filename)

        try:
            with http.request('GET', deb_url, preload_content=False) as r, open(filename_path, 'wb') as out_file:
                if r.status != 200:
                    self.logger.error("[%s] %s" % (r.status, deb_url))
                    return self.set_failure(filename_path)
                shutil.copyfileobj(r, out_file)
        except Exception as error:
            self.logger.exception(error)
            return self.set_failure(filename_path)

        if config['verify_file_mode'] == 'checksum':
            is_same, checksum = tools.checksha256(filename_path, fileinfo['checksum'])
            if not is_same: self.logger.error("%s %s but have %s" % (fileinfo['checksum'], filename_path, checksum))
        else:
            is_same, size = tools.checksize(filename_path, fileinfo['size'])
            if not is_same: self.logger.error("%s %s but have %s" % (fileinfo['size'], filename_path, size))

        if not is_same:
            os.remove(filename_path)
            return self.set_failure(filename_path)

        return True


    def package_to_list(self, packages_path):
        packages_data = open(packages_path, 'rb').read().decode('utf-8').splitlines()

        filenames = [line.split(': ')[1] for line in packages_data if line.startswith('Filename:')]
        checksums = [line.split(': ')[1] for line in packages_data if line.startswith('SHA256:')]
        sizes = [line.split(': ')[1] for line in packages_data if line.startswith('Size:')]

        filenames_length = len(filenames)
        checksums_length = len(checksums)
        sizes_length = len(sizes)

        if filenames_length != checksums_length or filenames_length != sizes_length:
            self.logger.error("%s : Erreur number of filename (%s) not equal number of checkum (%s) or size (%s) !" % (packages_path, filenames_length, checksums_length, sizes_length))
            return None, None

        files = {}
        for idx, filename in enumerate(filenames):
            files[filename] = {'checksum': checksums[idx], 'size': sizes[idx] }

        return filenames, files


    def process_packages(self, packages_path):

        packages_path_full = os.path.join(self.repo_tmp, packages_path)
        filenames, files = self.package_to_list(packages_path_full)
        if filenames == None: return self.set_failure(packages_path_full)

        self.need_download = list(set(filenames) - set(self.debians_present))

        if os.path.exists(os.path.join(self.repo_www, packages_path)):
            packages_path_full = os.path.join(self.repo_www, packages_path)

        filenames_old, files_old = self.package_to_list(packages_path_full)
        if filenames_old == None: return self.set_failure(packages_path_full)

        futures = []
        files_changed = [f for f in files_old if f in files and files_old[f] != files[f]]
        diff_file_set = set(files_changed + self.need_download)
        with concurrent.futures.ThreadPoolExecutor(max_workers=config['max_thread']) as executor:
            for f in files_old:
                if f in diff_file_set: continue
                if config['verify_file_mode'] == 'checksum':
                    futures.append(executor.submit(self.is_checksum, f, files_old[f]['checksum']))
                else: futures.append(executor.submit(self.is_size, f, files_old[f]['size']))

            for future in concurrent.futures.as_completed(futures):
                is_same, filename = future.result()
                if not is_same: files_changed.append(filename)

        self.need_download = list(set(self.need_download + files_changed))

        available_debs = {}
        for filename in self.need_download:
            os.makedirs(os.path.dirname(os.path.join(self.repo_tmp, filename)), exist_ok=True)
            available_debs[filename] = files[filename]

        if len(self.need_download) > 0:
            self.logger.warn("%s [%s debs | download %s]" % (packages_path, len(files), len(self.need_download)))
        else:
            self.logger.info("%s [%s debs]" % (packages_path, len(files)))

        with concurrent.futures.ThreadPoolExecutor(max_workers=config['max_thread']) as executor:
            process_debians, futures = [], []
            for f in available_debs:
                futures.append(executor.submit(self.get_deb, f, available_debs[f]))

            next_prc = -1
            total_length = len(futures)
            done_length = 0
            while done_length < total_length:
                done_length = len([True for future in futures if future.done()])

                prc = int(done_length / total_length * 100)
                if prc > next_prc or done_length == total_length:
                    logging.info("[%s%s] (%s/%s) Debians %s%%" % ('=' * prc, ' ' * (100-prc),
                        round(done_length, 2),
                        round(total_length, 2), prc))
                    next_prc = prc + 10

                sleep(1)

            for future in concurrent.futures.as_completed(futures):
                process_debians.append(future.result())

        if len([f for f in process_debians if f == False]) > 0:
            return self.set_failure(packages_path_full)

        return True


    def get_files(self, file_url, file_path):

        filename, extension = tools.splitext(file_path)

        if self.is_clone:
            try: 
                if extension != '' and extension in config['files_ext_search']:
                    file_path = filename    
                file_data = open(os.path.join(self.clone, file_path), 'rb').read()
            except Exception as error:
                self.logger.exception(error)
                return self.set_failure(os.path.join(self.clone, file_path))
        else:
            try:
                r = requests.get(file_url, proxies=proxies)
            except Exception as error:
                self.logger.exception(error)
                return self.set_failure(file_url)

            if r.status_code != 200:
                self.logger.error("[%s] %s" % (r.status_code, file_url))
                return self.set_failure(file_url)

            file_data = r.content
            if extension != '' and extension in config['files_ext_search']:
                file_data = tools.uncompress_data(file_data, extension)
                file_path = filename

        tools.save_file(os.path.join(self.repo_tmp, file_path), file_data)

        return True


    def get_release_infos(self, distribution, working_dir):

        dist_path = os.path.join(working_dir, 'dists' if self.components else '', distribution)
        release_path = os.path.join(dist_path, 'Release')

        if not os.path.exists(release_path):
            return self.set_failure(release_path)

        with open(release_path, 'r') as file:
            release = re.sub('[ ]+', ' ', yaml.safe_load(file)['SHA256']).split()

        checksums, sizes, filenames = [], [], []
        for i, l in enumerate(release):
            if i % 3 == 0: checksums.append(l)
            elif i % 3 == 1: sizes.append(l)
            else: filenames.append(l)

        if len(filenames) != len(checksums) or len(checksums) != len(sizes):
            self.logger.error(f"{working_dir} [{distribution}]: Erreur number of filename ({len(filenames)}) not equal number of checksum ({len(checksums)}) or size ({len(sizes)})!")
            return self.set_failure(release_path)

        filter_archs = '.*' if not self.archs else f'.*-({"|".join(self.archs)})(/|\\.|$)'
        filter_components = '.*' if not self.components else f'^({"|".join(self.components)})/'

        commands_files = '(^|.*/)Commands' + filter_archs
        icons_files = '.*/dep11/icons-([0-9]+)x([0-9]+).*.tar.gz'
        translation_files = '.*/Translation-(fr|en)(\\.|$)'
        packages_files = '(^|.*/)Packages(\\.[a-z0-9]+|)$'

        commands_list = [f for f in filenames if re.match(filter_components, f) and re.match(commands_files, f)]
        icons_list = [f for f in filenames if re.match(filter_components, f) and re.match(icons_files, f)]
        translation_list = [f for f in filenames if re.match(filter_components, f) and re.match(translation_files, f)]
        packages_list = [f for f in filenames if re.match(filter_components, f) and re.match(filter_archs, f) and re.match(packages_files, f)]

        filenames_exts = {}
        for filename in translation_list + commands_list + packages_list:
            f, e = tools.splitext(filename)
            filenames_exts.setdefault(f, []).append(e)
            filenames_exts[f] = list(set(config['files_ext_search']) & set(filenames_exts[f]))

        no_extensions = [{'filename': f, 'extension': ext} for f, ext in filenames_exts.items() if not ext]
        if no_extensions:
            self.logger.error(f"{working_dir} [{distribution}]: Erreur des extensions ne sont pas gérées ({no_extensions})!")
            return self.set_failure(release_path)

        self.icons_list = icons_list
        self.packages_list = []
        self.translation_list = []
        self.commands_list = []
        for f, ext in filenames_exts.items():
            filename = f"{f}{sorted(ext, reverse=True)[0]}"
            if filename in packages_list:
                self.packages_list.append(filename)
            elif filename in translation_list:
                self.translation_list.append(filename)
            elif filename in commands_list:
                self.commands_list.append(filename)

        if len(self.packages_list) == 0:
            self.logger.error("Aucun fichier Packages trouvé pour la distribution %s !" % (distribution))
            return self.set_failure(release_path)

        if len(self.components) > 0:
            for component in self.components:
                if len([p for p in self.packages_list if re.match(component + packages_files, p)]) == 0:
                    self.logger.error("[%s] [%s]: Aucun fichier Packages trouvé !" % (distribution, component))
                    return self.set_failure(release_path)

        return True

    def download_files(self, distribution, base_path, file_list):

        for f in file_list:
            os.makedirs(os.path.dirname(os.path.join(self.repo_tmp, base_path, distribution, f)), exist_ok=True)

        futures, res_download = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=config['max_thread']) as executor:
            for f in file_list:
                futures.append(executor.submit(self.get_files, 
                    os.path.join(self.url, base_path, distribution, f), 
                    os.path.join(base_path, distribution, f)))
            for future in concurrent.futures.as_completed(futures):
                res_download.append(future.result())

        return len([f for f in res_download if f == False]) == 0

    def sync(self):

        for distribution in self.distributions:

            # Reset state for next distribution
            self.failure = False
            # Remove temporary repository
            self.cleanup()

            base_path = '' if len(self.components) == 0 else 'dists'
            if not self.download_files(distribution, base_path, config['release_files']):
                continue

            if not self.get_release_infos(distribution, self.repo_tmp):
                continue

            if not self.download_files(distribution, base_path, \
                    self.translation_list + self.packages_list + \
                    self.commands_list + self.icons_list):
                continue

            for packages in self.packages_list:
                filename, e = tools.splitext(packages)
                packages_path = os.path.join(base_path, distribution, filename)
                if not self.process_packages(packages_path):
                    break

            # Move temporary repository to www
            self.apply_repo()

        return True
