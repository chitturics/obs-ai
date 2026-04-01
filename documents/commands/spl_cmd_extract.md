---
 command: extract
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/extract
 title: extract, kv
 download_date: 2026-02-03 09:06:27
---

 # extract

Extracts field-value pairs from the search results. The extract command works only on the _raw field. If you want to extract from another field, you must perform some field renaming before you run the  extract command.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Extract options

The extract command is a distributable streaming command. See Command types.

#### Alias

The alias for the extract command is kv.

#### 1. Specify the delimiters to use for the field and value extractions

Extract field-value pairs that are delimited by the pipe ( | ) or semicolon ( ; ) characters. Extract values of the fields that are delimited by the equal ( = ) or colon ( : ) characters.  The delimiters are individual characters.  In this example the "=" or ":" character is used to delimit the key value.  Similarly, a "|" or ";" is used to delimit the field-value pair itself.

#### 2. Extract field-value pairs and reload the field extraction settings

Extract field-value pairs and reload field extraction settings from disk.

#### 3. Rename a field to _raw to extract from that field

Rename the _raw field to a temporary name. Rename the field you want to extract from, to _raw. In this example the field name is uri_query.

... | rename _raw AS temp uri_query AS _raw | extract pairdelim="?&" kvdelim="=" | rename _raw AS uri_query temp AS _raw

#### 4. Extract field-value pairs from a stanza in the transforms.conf file

Extract field-value pairs that are defined in the my-access-extractions stanza in the transforms.conf file.

The transforms.conf stanza for this example looks something like this.

kvform, multikv, rex,  spath, xmlkv,  xpath
 