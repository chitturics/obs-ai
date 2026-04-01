---
 command: fromjson
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Fromjson
 title: fromjson
 download_date: 2026-02-03 09:08:21
---

 # fromjson

# fromjson

## Description

Converts JSON-formatted objects into multivalue fields. If you give the fromjson command a single field name that points to proper JSON objects, fromjson returns keys as fields and key values as field values.

## Syntax

Required syntax is in bold.

| fromjson<string>

[ prefix=<string>]

### Optional arguments

Syntax: prefix=<string>

Description: Prepends a string to the fields that  fromjson extracts from a JSON-formatted object. For example, including prefix=my_ in the search adds my_ to the beginning of field names in the results.

Default: none

## Usage

The fromjson command is a streaming command, which means that it turns JSON-formatted objects into fields as each JSON object is received. See Types of commands.

## Examples

### 1. Expand a JSON object to create new fields

Use the fromjson command to expand a JSON-formatted object and return the values in the search result. This example creates two new fields called name and age, and outputs the corresponding values in the search results.

The results look like this.

### 2. Prepend the name of extracted fields

You can use the optional argument prefix to prepend a string to fields extracted from a JSON-formatted object. This example creates two new fields called json_name and json_age.

The results look something like this.

### 3. Expand nested JSON objects

When you use fromjson to expand JSON-formatted objects into multivalue fields, you can retain the formatting of JSON objects by nesting them within the main object. In the following example, the object called json_obj with the key-value pair "school" and "city",  is nested within another JSON object called object.

The results look something like this.

["math","history","science"],"another_json_object":{"school":"city"},"null":null}

## See also

Evaluation functions

JSON functions
 