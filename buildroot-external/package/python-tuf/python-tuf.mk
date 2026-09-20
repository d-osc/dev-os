# Generated from config/runtime-sources.json; do not edit by hand.
PYTHON_TUF_VERSION = 7.0.1
PYTHON_TUF_SOURCE = tuf-7.0.1.tar.gz
PYTHON_TUF_SITE = https://files.pythonhosted.org/packages/9c/dd/52e7390cbac308e6b1cfe6be9bc3a96fe26326d5893cc297a52bb72792a9
PYTHON_TUF_SETUP_TYPE = pep517
PYTHON_TUF_LICENSE = Apache-2.0 or MIT
PYTHON_TUF_LICENSE_FILES = LICENSE LICENSE-MIT
PYTHON_TUF_DEPENDENCIES = python-securesystemslib python-urllib3 host-devos-hatchling132
PYTHON_TUF_ENV = PYTHONPATH="$(HOST_DIR)/lib/devos/hatchling132:$(PYTHON3_PATH)"

$(eval $(python-package))
