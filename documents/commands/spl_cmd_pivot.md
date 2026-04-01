---
 command: pivot
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/pivot
 title: pivot
 download_date: 2026-02-03 09:13:45
---

 # pivot

The pivot command makes simple pivot operations fairly straightforward, but can be pretty complex for more sophisticated pivot operations. Fundamentally this command is a wrapper around the stats and xyseries commands.

The pivot command does not add new behavior, but it might be easier to use if you are already familiar with how Pivot works. See the Pivot Manual. Also, read how to open non-transforming searches in Pivot.

Run pivot searches against a particular data model object. This requires a large number of inputs: the data model, the data model object, and pivot elements.

| pivot <datamodel-name> <object-name> <pivot-element>

#### Required arguments

#### Cell value

The set of allowed functions depend on the data type of the fieldname:

- Strings: list, values, first, last, count, and distinct_count (dc)
- Numbers: sum, count, avg, max, min, stdev, list, and values
- Timestamps: duration, earliest, latest, list, and values
- Object or child counts: count

#### Descriptions for row split-by elements

Other options depend on the data type of the <field> specified:

- RANGE applies only for numbers. You do not need to specify all of the options (start, end, max, and size).
- PERIOD applies only for timestamps. Use it to specify the period to bucket by.
- TRUELABEL applies only for booleans. Use it to specify the label for true values.
- FALSELABEL applies only for booleans. Use it to specify the label for false values.

#### Descriptions for column split-by elements

Other options depend on the data type of the field specified (fieldname):

- RANGE applies only for numbers. The options (start, end, max, and size) do not all have to be specified.
- PERIOD applies only for timestamps. Use it to specify the period to bucket by.
- TRUELABEL applies only for booleans. Use it to specify the label for true values.
- FALSELABEL applies only for booleans. Use it to specify the label for false values.

#### Descriptions for filter elements

- Strings: is, contains, in, isNot, doesNotContain, startsWith, endsWith, isNull, isNotNull

- ipv4: is, contains, isNot, doesNotContain, startsWith, isNull, isNotNull
- Numbers: =, !=, <, <=, >, >=, isNull, isNotNull
- Booleans: is, isNull, isNotNull

#### Descriptions for limit elements

The pivot command is a report-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

Example 1: This command counts the number of events in the "HTTP Requests" object in the "Tutorial" data model.

This can be formatted as a single value report in the dashboard panel:

datamodel, stats, xyseries
 