---
 command: fields
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/fields
 title: fields
 download_date: 2026-02-03 09:06:42
---

 # fields

Keeps or removes fields  from search results based on the field list criteria.

By default, the internal fields _raw and _time are included in output in Splunk Web. Additional internal fields are included in the output with the outputcsv command. See Usage.

fields [+|-] <wc-field-list>

#### Required arguments

#### Optional arguments

The fields command is a distributable streaming command. See Command types.

#### Internal fields and Splunk Web

The leading underscore is reserved for names of internal fields such as _raw and _time. By default, the internal fields _raw and _time are included in the search results in Splunk Web.  The fields command does not remove these internal fields unless you explicitly specify that the fields should not appear in the output in Splunk Web.

For example, to remove all internal fields, you specify:

... | fields - _*

To exclude a specific field, such as _raw, you specify:

... | fields - _raw

Note: Be cautious removing the _time field. Statistical commands, such as timechart and chart, cannot display date or time information without the _time field.

#### Displaying internal fields in Splunk Web

Other than the _raw and _time fields, internal fields do not display in Splunk Web, even if you explicitly specify the fields in the search. For example, the following search does not show the _bkt field in the results.

To display an internal field in the results, the field must be copied or renamed to a field name that does not include the leading underscore character. For example:

#### Internal fields and the outputcsv command

When the outputcsv command is used in the search, there are additional internal fields that are automatically added to the CSV file. The most common internal fields that are added are:

- _raw
- _time
- _indextime

#### You cannot match wildcard characters in searches that use the fields command

You can use the asterisk ( * ) in your searches as a wildcard character, but you can't use a backslash ( \ ) to escape an asterisk in search strings. A backslash\ and an asterisk * match the characters \* in searches, not an escaped wildcard * character. Because Splunk platform doesn't support escaping wildcards, asterisk ( * ) characters in field names can't be matched in searches that keep or remove fields from search results.

#### Support for backslash characters ( \ ) in the fields command

To match a backslash character ( \ ) in a field name when using the fields command, use 2 backslashes for each backslash. For example, to display fields that contain http:\\, use the following command in your search:

See Backslashes in the Search Manual.

#### Example 1:

Remove the host and ip fields from the results

#### Example 2:

Keep only the host and ip fields. Remove all of the internal fields. The internal fields begin with an underscore character, for example _time.

#### Example 3:

Remove unwanted internal fields from the output CSV file. The fields to exclude are _raw_indextime, _sourcetype, _subsecond, and _serial.

index=_internal sourcetype="splunkd" | head 5 | fields - _raw, _indextime, _sourcetype, _subsecond, _serial | outputcsv MyTestCsvfile

#### Example 4:

Keep only the fields source, sourcetype, host, and all fields beginning with error.

rename,
table
 