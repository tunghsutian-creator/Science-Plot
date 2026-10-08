"""Fixed test scientific pipeline; invoked only through its sealed file identity."""

import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--request", required=True)
parser.add_argument("--response", required=True)
args = parser.parse_args()
with open(args.request) as stream:
    request = json.load(stream)
columns = request["input"]["columns"]
factor = request["parameters"]["factor"]
column = columns["column:1"]
column["values"] = [None if value is None else value * factor for value in column["values"]]
column["unit"] = "1"
with open(args.response, "w") as stream:
    json.dump({"kind": "sciplot_transform_response", "schema_version": 1,
               "request_sha256": request["request_sha256"], "columns": columns}, stream, allow_nan=False)
