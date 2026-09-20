# Pinned, isolated host-only wheel; never installed into the target image.
HOST_DEVOS_HATCHLING131_VERSION = 1.31.0
HOST_DEVOS_HATCHLING131_SOURCE = hatchling-1.31.0-py3-none-any.whl
HOST_DEVOS_HATCHLING131_SITE = https://files.pythonhosted.org/packages/64/e2/2c0af0a52d16be74a4f194564fcdc417521ed863e9b65e4bc9052dacba6f
HOST_DEVOS_HATCHLING131_LICENSE = MIT
HOST_DEVOS_HATCHLING131_LICENSE_FILES = hatchling-1.31.0.dist-info/licenses/LICENSE.txt
HOST_DEVOS_HATCHLING131_DEPENDENCIES = host-python3 host-python-packaging host-python-pathspec host-python-pluggy host-python-trove-classifiers host-python-tomlkit

define HOST_DEVOS_HATCHLING131_EXTRACT_CMDS
	python3 -m zipfile -e $(HOST_DEVOS_HATCHLING131_DL_DIR)/$(HOST_DEVOS_HATCHLING131_SOURCE) $(@D)
endef

define HOST_DEVOS_HATCHLING131_INSTALL_CMDS
	mkdir -p $(HOST_DIR)/lib/devos/hatchling131
	cp -a $(@D)/hatchling $(@D)/hatchling-1.31.0.dist-info $(HOST_DIR)/lib/devos/hatchling131/
endef

$(eval $(host-generic-package))
