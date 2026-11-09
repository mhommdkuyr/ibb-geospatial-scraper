"""
Configuration module for Ibb Governorate & City Geospatial Scraper.
Defines geographic bounding boxes, high-density commercial corridors,
zoom levels, and system constants.
"""

from typing import Dict, List, Tuple

# Bounding Box for Greater Ibb Governorate (Rural / General Coverage)
IBB_GOVERNORATE_BBOX = {
    "min_lat": 13.7000,
    "max_lat": 14.4000,
    "min_lng": 43.8000,
    "max_lng": 44.6000,
    "grid_step_m": 500,  # 500m x 500m for rural / general governorate
    "zoom": 17,
}

# Bounding Box for Ibb City General Urban Envelope
IBB_CITY_BBOX = {
    "min_lat": 13.9300,
    "max_lat": 14.0300,
    "min_lng": 44.1300,
    "max_lng": 44.2300,
    "grid_step_m": 120,  # 120m x 120m for general city sectors
    "zoom": 19,
}

# Ultra-High-Density Commercial Corridors in Ibb City (40m x 40m Micro-Grid)
# Step: ~0.00036° (~40 meters) at 20z-21z
DENSE_CORRIDORS: Dict[str, Dict] = {
    "shari_taiz": {
        "name_ar": "شارع تعز (المدخل الجنوبي حتى قلب المدينة)",
        "min_lat": 13.9450,
        "max_lat": 13.9750,
        "min_lng": 44.1680,
        "max_lng": 44.1820,
        "grid_step_m": 40,
        "zoom": 21,
    },
    "shari_al_odayn": {
        "name_ar": "شارع العدين (الشريان التجاري المركزي ومحلات الذهب والجوالات)",
        "min_lat": 13.9620,
        "max_lat": 13.9780,
        "min_lng": 44.1600,
        "max_lng": 44.1780,
        "grid_step_m": 40,
        "zoom": 21,
    },
    "shari_al_thalatheen": {
        "name_ar": "شارع الثلاثين (المنطقة التجارية الجديدة والشركات)",
        "min_lat": 13.9700,
        "max_lat": 13.9950,
        "min_lng": 44.1500,
        "max_lng": 44.1850,
        "grid_step_m": 40,
        "zoom": 21,
    },
    "al_dairi_al_gharbi_sharqi": {
        "name_ar": "الدائري الغربي والشرقي (المعارض والخدمات العامة)",
        "min_lat": 13.9550,
        "max_lat": 13.9850,
        "min_lng": 44.1550,
        "max_lng": 44.1950,
        "grid_step_m": 45,
        "zoom": 21,
    },
    "al_maayin": {
        "name_ar": "حي ومنطقة المعاين (التوسعات التجارية والمراكز الطبية)",
        "min_lat": 13.9850,
        "max_lat": 14.0150,
        "min_lng": 44.1600,
        "max_lng": 44.1850,
        "grid_step_m": 45,
        "zoom": 21,
    },
    "al_jabanah_and_old_city": {
        "name_ar": "الجبانة ومركز المدينة التاريخي (الأسواق الحرفية والشعبية)",
        "min_lat": 13.9650,
        "max_lat": 13.9750,
        "min_lng": 44.1700,
        "max_lng": 44.1820,
        "grid_step_m": 35,
        "zoom": 21,
    },
    "al_subol": {
        "name_ar": "شارع السبل (مجمعات الورش وقطع الغيار والتجارة الحرفية)",
        "min_lat": 13.9500,
        "max_lat": 13.9700,
        "min_lng": 44.1450,
        "max_lng": 44.1650,
        "grid_step_m": 45,
        "zoom": 21,
    },
    "mafraq_jiblah": {
        "name_ar": "مفرق جبلة ومثلث المواصلات التجاري",
        "min_lat": 13.9350,
        "max_lat": 13.9550,
        "min_lng": 44.1650,
        "max_lng": 44.1850,
        "grid_step_m": 40,
        "zoom": 21,
    },
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

SOCS_COOKIE = "CAESHAgBEhJnd3NfMjAyNDA5MTAtMF9SQzEaAmFyIAEaBgiA_K-1Bg"
