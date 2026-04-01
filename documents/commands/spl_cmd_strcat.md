---
 command: strcat
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/strcat
 title: strcat
 download_date: 2026-02-03 09:18:05
---

 # strcat

Concatenates string values from 2 or more fields. Combines together string values and literals into a new field. A destination field name is specified at the end of the strcat command.

strcat [allrequired=<bool>] <source-fields> <dest-field>

#### Required arguments

#### Optional arguments

The strcat command is a distributable streaming command. See Command types.

#### Example 1:

Add a field called comboIP, which combines the source and destination IP addresses. Separate the addresses with a forward slash character.

#### Example 2:

Add a  field called comboIP,  which combines the source and destination IP addresses. Separate the addresses with a forward slash character. Create a chart of the number of occurrences of the field values.

#### Example 3:

Add a field called address, which combines the host and port values into the format <host>::<port>.
 