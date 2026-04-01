---
 command: rex
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/rex
 title: rex
 download_date: 2026-02-03 09:15:51
---

 # rex

Use this command to either extract fields using regular expression named groups, or replace or substitute characters in a field using sed expressions.

The rex command matches the value of the specified field against the unanchored regular expression and extracts the named groups into fields of the corresponding names.

When mode=sed, the given sed expression used to replace or substitute characters is applied to the value of the chosen field. This sed-syntax is also used to mask, or anonymize, sensitive data at index-time. Read about using sed to anonymize data in the Getting Data In Manual.

Note: If a field is not specified, the regular expression or sed expression is applied to the _raw field. Running the rex command against the _raw field might have a performance impact.

Use the rex command for search-time field extraction or string replacement and character substitution.

The required syntax is in bold.

#### Required arguments

You must specify either <regex-expression> or mode=sed <sed-expression>.

#### Optional arguments

The rex command is a distributable streaming command. See Command types.

#### rex command or regex command?

Use the rex command to either extract fields using regular expression named groups, or replace or substitute characters in a field using sed expressions.

Use the regex command to remove results that do not match the specified regular expression.

#### Regular expressions

Splunk SPL supports perl-compatible regular expressions (PCRE).

When you use regular expressions in searches, you need to be aware of how characters such as pipe ( | ) and backslash ( \ ) are handled.  See SPL and regular expressions in the Search Manual.

For general information about regular expressions, see  About Splunk regular expressions in the Knowledge Manager Manual.

#### Sed expressions

When using the rex command in sed mode, you have two options: replace (s) or character substitution (y).

The syntax for using sed to replace (s) text in your data is: "s/<regex>/<replacement>/<flags>"

- <regex> is a PCRE regular expression, which can include capturing groups.
- <replacement> is a string to replace the regex match. Use \n for back references, where "n" is a single digit.
- <flags> can be either g to replace all matches, or a number to replace a specified match.

The syntax for using sed to substitute characters is: "y/<string1>/<string2>/"

- This substitutes the characters that match <string1> with the characters in <string2>.

When using the rex command in sed mode, the rex command supports the same sed expressions as the SEDCMD setting in the props.conf.in file.

#### Anonymize multiline text using sed expressions

The Splunk platform doesn't support applying sed expressions in multiline mode. To use a sed expression to anonymize multiline events, use 2 sed expressions in succession by first removing the newlines and then performing additional replacements. For example, the following search uses the rex command to replace all newline characters in a multiline event containing HTML content, and then redacts all of the HTML content.

index=main html 
| rex mode=sed field=_raw "s/\\n/NEWLINE_REMOVED/g" 
| rex mode=sed field=_raw "s/<html.*html>/REDACTED/g"

#### 1. Extract email values using regular expressions

Extract email values from events to create from and to fields in your events. For example, you have events such as:

When the events were indexed, the From and To values were not identified as fields.  You can use the rex command to extract the field values and create from and to fields in your search results.

The from and to lines in the _raw events follow an identical pattern. Each from line is From: and each to line is To:. The email addresses are enclosed in angle brackets.  You can use this pattern to create a regular expression to extract the values and create the fields.

source="cisco_esa.txt" | rex field=_raw "From: <(?<from>.*)> To: <(?<to>.*)>"

You can remove duplicate values and return only the list of address by adding the dedup and table commands to the search.

source="cisco_esa.txt" | rex field=_raw "From: <(?<from>.*)> To: <(?<to>.*)>" | dedup from to | table from to

The results look something like this:

#### 2. Extract from multi-valued fields using max_match

You can use the max_match argument to specify that the regular expression runs multiple times to extract multiple values from a field.

For example, use the makeresults command to create a field with multiple values:

| _time | test |
| --- | --- |
| 2019-12-05 11:15:28 | a$1,b$2 |

To extract each of the values in the test field separately, you use the max_match argument with the rex command.  For example:

...| rex field=test max_match=0 "((?<field>[^$]*)\$(?<value>[^,]*),?)"

The results look something like this:

| _time | field | test | value |
| --- | --- | --- | --- |
| 2019-12-05 11:36:57 | a
b | a$1,b$2 | 1
2 |

#### 3. Extract values from a field in scheduler.log events

Extract "user", "app" and "SavedSearchName" from a field called "savedsearch_id" in scheduler.log events. If savedsearch_id=bob;search;my_saved_search then user=bob , app=search and SavedSearchName=my_saved_search

... | rex field=savedsearch_id "(?<user>\w+);(?<app>\w+);(?<SavedSearchName>\w+)"

#### 4. Use a sed expression

Use sed syntax to match the regex to a series of numbers and replace them with an anonymized string.

... | rex field=ccnumber mode=sed "s/(\d{4}-){3}/XXXX-XXXX-XXXX-/g"

#### 5. Use a sed expression with capture replace for strings

This example shows how to use the rex command sed expression with capture replace using \1, \2 to reuse captured pieces of a string.

This search creates an event with three fields, _time, search, and orig_search. The regular expression removes the quotation marks and any leading or trailing spaces around the quotation marks.

|makeresults
|eval orig_search="src_ip=TERM( \"10.8.2.33\" ) OR src_ip=TERM( \"172.17.154.197\" )", search=orig_search
|rex mode=sed field=search "s/\s\"(\d+\.\d+\.\d+\.\d+)\"\s/\1/g"

The results look like this:

| _time | orig_search | search |
| --- | --- | --- |
| 2021-05-31 23:36:29 | src_ip=TERM( "10.8.2.33" ) OR src_ip=TERM( "172.17.154.197" ) | src_ip=TERM(10.8.2.33) OR src_ip=TERM(172.17.154.197) |

#### 6. Use an offset_field

To identify the position of certain values in a field, use the rex command  with the offset_field argument and a regular expression.

The following example starts with the makeresults command to create a field with a value:

| makeresults
| eval list="abcdefghijklmnopqrstuvwxyz"

The results look something like this:

| _time | list |
| --- | --- |
| 2022-05-21 11:36:57 | abcdefghijklmnopqrstuvwxyz |

Add the rex command with the offset_field argument to the search to create a field called off. You can identify the position of the first five values in the field list using the regular expression "(?<firstfive>abcde)". For example:

| makeresults
| eval list="abcdefghijklmnopqrstuvwxyz"
| rex offset_field=off field=list "(?<firstfive>abcde)"

The results look something like this:

| _time | firstfive | list | off |
| --- | --- | --- | --- |
| 2022-05-21 11:36:57 | abcde | abcdefghijklmnopqrstuvwxyz | firstfive=0-4 |

You can identify the position of several of the middle values in the field list using the regular expression "(?<middle>fgh)". For example:

| makeresults
| eval list="abcdefghijklmnopqrstuvwxyz"
| rex offset_field=off field=list "(?<middle>fgh)"

The results look something like this:

| _time | list | middle | off |
| --- | --- | --- | --- |
| 2022-05-21 11:36:57 | abcdefghijklmnopqrstuvwxyz | fgh | middle=5-7 |

#### 7. Display IP address and ports of potential attackers

Display IP address and ports of potential attackers.

sourcetype=linux_secure port "failed password" | rex "\s+(?<ports>port \d+)" | top src_ip ports showperc=0

This search uses the rex command to extract the port field and values. The search returns a table that lists the top source IP addresses (src_ip) and ports of the potential attackers.
 