---
 command: rare
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/rare
 title: rare
 download_date: 2026-02-03 09:14:17
---

 # rare

Displays the least common values in a field.

Finds the least frequent tuple of values of all fields in the field list. If the <by-clause> is specified, this command returns rare tuples of values for each distinct tuple of values of the group-by fields.

This command operates identically to the top command, except that the rare command finds the least frequent values instead of the most frequent values.

rare [<rare-options>...] <field-list> [<by-clause>]

#### Required arguments

#### Optional arguments

#### Rare options

The rare command is a transforming command. See Command types.

#### Limit maximum

The number of results returned by the rare command is controlled by the limit argument. The default value for the limit argument is 10. The default maximum is 50,000, which effectively keeps a ceiling on the memory that the rare command uses.

You can change this limit up to the maximum value specified in the  maxresultrows setting in the [rare] stanza in the  limits.conf file.

- Open or create a local limits.conf file in the desired path. For example, use the $SPLUNK_HOME/etc/apps/search/local path to apply this change only to the Search app.
- Under the [rare] stanza, change the value for the maxresultrows setting.

#### 1. Return the least common values in a field

Return the least common values in the url field. Limits the number of values returned to 5.

#### 2. Return the least common values organized by host

Find the least common values in the user field for each host value. By default, a maximum of 10 results are returned.
 