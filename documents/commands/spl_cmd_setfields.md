---
 command: setfields
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/setfields
 title: setfields
 download_date: 2026-02-03 09:16:58
---

 # setfields

Sets the field values for all results to a common value.

Sets the value of the given fields to the specified values for each event in the result set. Delimit multiple definitions with commas. Missing fields are added, present fields are overwritten.

Whenever you need to change or define field values, you can use the more general purpose eval command. See usage of an eval expression to set the value of a field in Example 1.

setfields <setfields-arg>, ...

#### Required arguments

#### Example 1:

Specify a value for the ip and foo fields.

To do this with the eval command:

eval,
fillnull,
rename
 