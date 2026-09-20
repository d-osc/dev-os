# Pinned, isolated host-only wheel; never installed into the target image.
HOST_DEVOS_HATCHLING132_VERSION = 1.32.0
HOST_DEVOS_HATCHLING132_SOURCE = hatchling-1.32.0-py3-none-any.whl
HOST_DEVOS_HATCHLING132_SITE = https://files.pythonhosted.org/packages/a9/84/1798b6d85ecde0e31546004efd25c5de1b1f49250644a60cce460e12593a
HOST_DEVOS_HATCHLING132_LICENSE = MIT
HOST_DEVOS_HATCHLING132_LICENSE_FILES = hatchling-1.32.0.dist-info/licenses/LICENSE.txt
HOST_DEVOS_HATCHLING132_DEPENDENCIES = host-python3 host-python-packaging host-python-pathspec host-python-pluggy host-python-trove-classifiers host-python-tomlkit

define HOST_DEVOS_HATCHLING132_EXTRACT_CMDS
	python3 -m zipfile -e $(HOST_DEVOS_HATCHLING132_DL_DIR)/$(HOST_DEVOS_HATCHLING132_SOURCE) $(@D)
endef

define HOST_DEVOS_HATCHLING132_INSTALL_CMDS
	mkdir -p $(HOST_DIR)/lib/devos/hatchling132
	cp -a $(@D)/hatchling $(@D)/hatchling-1.32.0.dist-info $(HOST_DIR)/lib/devos/hatchling132/
endef

$(eval $(host-generic-package))
