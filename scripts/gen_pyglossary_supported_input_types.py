#!/usr/bin/env python3

import requests
import json

url = 'https://raw.githubusercontent.com/ilius/pyglossary/master/plugins-meta/index.json'
response = requests.get(url)
data = response.json()

result = {}
for plugin in data:
    name = plugin['name']
    if name and plugin['canRead']:
        extensions = plugin['extensions']
        description = plugin['description']
        if not description:
            description = name
        if '(' not in description and len(extensions) > 0:
            value = description + "(" + ', '.join(extensions) + ")"
        else:
            value = description
        result[name] = value

print(", ".join(result.values()))
