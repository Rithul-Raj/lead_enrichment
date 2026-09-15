# config.example.py
# ------------------
# Copy this file to config.py and fill in your keys.
#
# SERPAPI_KEY : https://serpapi.com/manage-api-key
# PSI_API_KEY : https://console.cloud.google.com  (PageSpeed Insights API, free)
#
# IMPORTANT: config.py is in .gitignore — never commit real keys!

import os
SERPAPI_KEY = "your_serpapi_key_here"
PSI_API_KEY = os.environ.get("PSI_API_KEY", "")   # set via: $env:PSI_API_KEY="key"
