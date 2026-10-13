# GeoPort only resolves locale country codes. Do not ship unused translations.
from PyInstaller.utils.hooks import collect_data_files
datas = collect_data_files('pycountry', includes=['databases/iso3166-1.json'])
