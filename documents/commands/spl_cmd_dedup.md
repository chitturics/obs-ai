---
 command: dedup
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/dedup
 title: dedup
 download_date: 2026-02-03 09:04:35
---

 # dedup

Removes the events that contain an identical combination of values for the fields that you specify.

With the  dedup command, you can specify the number of duplicate events to keep for each value of a single field, or for each combination of values among several fields.  Events returned by dedup are based on search order. For historical searches, the most recent events are searched first. For real-time searches, the first events that are received are searched, which are not necessarily the most recent events.

You can specify the number of events with duplicate values, or value combinations, to keep. You can sort the fields, which determines which event is retained.  Other options enable you to retain events with the duplicate fields removed, or to keep events where the fields specified do not exist in the events.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Sort field options

The dedup command is a streaming command or a  dataset processing command, depending on which arguments are specified with the command. For example, if you specify the <sort-by-clause, the dedup command acts as a dataset processing command. All of the results must be collected before sorting. See Command types.

Avoid using the dedup command on the _raw field if you are searching over a large volume of data. If you search the  _raw field, the text of every event in memory is retained which impacts your search performance. This is expected behavior.  This behavior applies to any field with high cardinality and large size.

#### Multivalue fields

To use the dedup command on multivalue fields, the fields must match all values to be deduplicated.

#### Lexicographical order

Lexicographical order sorts items based on the values used to encode the items in computer memory. In Splunk software, this is almost always UTF-8 encoding, which is a superset of ASCII.

- Numbers are sorted before letters. Numbers are sorted based on the first digit. For example, the numbers 10, 9, 70, 100 are sorted lexicographically as 10, 100, 70, 9.
- Uppercase letters are sorted before lowercase letters.
- Symbols are not standard. Some symbols are sorted before numeric values. Other symbols are sorted before or after letters.

#### 1. Remove duplicate results based on one field

Remove duplicate search results with the same host value.

#### 2. Remove duplicate results and sort results in ascending order

Remove duplicate search results with the same source value and sort the results by the _time field in ascending order.

#### 3. Remove duplicate results and sort results in descending order

Remove duplicate search results with the same source value and sort the results by the _size field in descending order.

#### 4. Keep the first 3 duplicate results

For search results that have the same source value, keep the first 3 that occur and remove all subsequent results.

#### 5. Keep results that have the same combination of values in multiple fields

For search results that have the same source AND host values, keep the first 2 that occur and remove all subsequent results.

#### 6. Remove only consecutive duplicate events

Remove only consecutive duplicate events. Keep non-consecutive duplicate events. In this example duplicates must have the same combination of values the  source and host fields.
 