#!/bin/python3

import os
import logging
import yaml
import zlib
import shutil
import lib.repo as aptme
import lib.tools as tools

logging.basicConfig(format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s', level=logging.INFO)

if not os.path.exists('config.yaml'):
    logging.error('Le fichier config.yaml est manquant !')
    exit(1)

config = yaml.safe_load(open('config.yaml', 'r'))

if not config['clean']:
    logging.info("Le mode clean est disable, simulate ...")

if not os.path.exists(config['www_dir']):
    logging.info("Data dir not present, exit ...")
    exit(0)

debians_list = []
packages_list = []
debians_present = []
packages_present = []
for repo in config['repos']:

    r_manager = aptme.repositoryManager(repo)
    r_manager.initialize()

    debians_present.extend([os.path.join(r_manager.repo_www, x) for x in r_manager.debians_present])
    packages_present.extend(r_manager.packages_present)

    for distribution in r_manager.distributions:
        if not r_manager.get_release_infos(distribution, r_manager.repo_www):
            continue

        base_path = '' if len(r_manager.components) == 0 else 'dists'
        for packages in r_manager.packages_list:
            packages_path, extension = os.path.splitext(os.path.join(r_manager.repo_www, base_path, distribution, packages))
            filenames, files = r_manager.package_to_list(packages_path)
            debians_list.extend([os.path.join(r_manager.repo_www, x) for x in filenames])
            packages_list.append(packages_path)

    del r_manager

debians_list = list(set(debians_list))
packages_list = list(set(packages_list))
debians_present = list(set(debians_present))
packages_present = list(set(packages_present))

missing_debians = list(set(debians_list) - set(debians_present))
missing_packages = list(set(packages_list) - set(packages_present))
unused_debians = list(set(debians_present) - set(debians_list))
unused_packages = list(set(packages_present) - set(packages_list))

tools.remove_when_not_missing('debians', missing_debians, unused_debians)
tools.remove_when_not_missing('Packages', missing_packages, unused_packages)

for repo in os.listdir(config['www_dir']):
    repo_path = os.path.join(config['www_dir'], repo)
    if not os.path.isdir(repo_path) or os.path.islink(repo_path):
        continue

    if repo in config['clean_ignore_dirs']:
        continue

    if repo in set([aptme.repositoryManager(repo).name for repo in config['repos']]):
        continue

    logging.info("Suppression du repository non utilisé: %s" % repo)
    if config['clean']:
        shutil.rmtree(repo_path)

logging.info('#######################"')
logging.info("Finished")
logging.info('#######################"')
