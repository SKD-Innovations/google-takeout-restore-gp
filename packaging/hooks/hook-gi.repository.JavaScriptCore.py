from PyInstaller.utils.hooks.gi import GiModuleInfo
module_info = GiModuleInfo('JavaScriptCore', '4.1')
binaries, datas, hiddenimports = module_info.collect_typelib_data()
