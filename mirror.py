#!/bin/python3

import os
import logging
import requests
import yaml
import shutil
from time import sleep
import gzip
import glob

import lib.tools as tools
import lib.repo as aptme

logging.basicConfig(format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s', level=logging.INFO)

if not os.path.exists('config.yaml'):
    logging.error('Le fichier config.yaml est manquant !')
    exit(1)

config = yaml.safe_load(open('config.yaml', 'r'))

if os.path.exists(config['tmp_dir']): shutil.rmtree(config['tmp_dir'])

os.makedirs(config['www_dir'], exist_ok=True)
os.makedirs(config['tmp_dir'], exist_ok=True)

repo_errors = []
for repo in config['repos']:

    r_manager = aptme.repositoryManager(repo)

    # Init repository
    r_manager.initialize()

    # Download distribution
    r_manager.sync()

    # Remove temporary repository
    r_manager.cleanup()

    if not r_manager.ignore_error:
        repo_errors.extend(r_manager.error_files)

    del r_manager

# Clean tmp_dir
if os.path.exists(config['tmp_dir']):
    shutil.rmtree(config['tmp_dir'])

# Configure alias
tools.configure_alias(config['alias'], config['www_dir'])

logging.info('#######################"')
# Show errors
for f in repo_errors:
    logging.error(f)

logging.info("Finished")
logging.info('#######################"')

exit(len(repo_errors))
