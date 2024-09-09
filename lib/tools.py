#!/bin/python3

import os
import zlib
import lzma
import bz2
import hashlib
import logging
import shutil
import sys

def checkmd5(filename_path, checksum):
    md5 = hashlib.md5(open(filename_path, 'rb').read()).hexdigest()
    return checksum == md5, md5

def checksha256(filename_path, checksum):
    sha256 = hashlib.sha256(open(filename_path, 'rb').read()).hexdigest()
    return checksum == sha256, sha256

def checksize(filename_path, size):
    size_file = os.stat(filename_path).st_size
    return int(size_file) == int(size), int(size_file)

def uncompress_data(data, extension):
    if extension == '.gz':
        return zlib.decompress(data, 16+zlib.MAX_WBITS)
    elif extension == '.xz':
        return lzma.decompress(data)
    elif extension == '.bz2':
        return bz2.decompress(data)
    else:
        logging.error("Unkown file extension %s" % extension)
        exit(1)

def save_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(data)

def merge_dir(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True, copy_function = shutil.move)

def remove_when_not_missing(type_file, missing, unused, clean):
    if len(missing) > 0:
        logging.info("Des fichiers %s semblent manquant, pas de suppression." % type_file)
        for f in missing:
            logging.info("%s: missing" % f)
    else:
        if len(unused) > 0:
            logging.info("Des fichiers %s existent mais ne sont pas utile ..." % type_file)
            for f in unused:
                logging.info("%s: suppression ..." % f)
                if clean:
                    os.remove(f)

def configure_alias(aliases, www_dir):

    for alias in aliases:

        alias_link = os.path.join(www_dir, alias['link'])

        logging.info("Create alias: %s => %s" % (alias_link, alias['to']))

        if '/' in alias['to'] or '/' in alias['link']:
            logging.error("Error subdirectory not accepted, skipped ...")
            continue

        if os.path.isdir(alias_link) and not os.path.islink(alias_link):
            logging.error("Error link is a dir, skipped ...")
            continue

        if os.path.exists(alias_link) and not os.path.islink(alias_link):
            logging.error("Error link is a file, recrate ...")
            os.remove(alias_link)

        if os.path.islink(alias_link) and not os.path.exists(alias_link):
            logging.error("Error link is dead")
            os.remove(alias_link)

        if os.path.islink(alias_link) and alias['to'] != os.readlink(alias_link):
            logging.error("Error link is bad %s != %s" % (os.readlink(alias_link), alias['to']))
            os.remove(alias_link)

        if not os.path.islink(alias_link):
            os.symlink(alias['to'], alias_link)
