---
 command: mcatalog
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Mcatalog
 title: mcatalog
 download_date: 2026-02-03 09:11:19
---

 # mcatalog

CAUTION: The mcatalog command is an internal, unsupported, experimental command. See 
About internal commands.

The mcatalog command performs aggregations on the values in the metric_name and dimension fields in the metric indexes.

| mcatalog [prestats=<bool>] [append=<bool>] ( <values"("<field> ")"> [AS <field>] )

#### Required arguments

#### Optional arguments

#### Logical expression options

#### Comparison expression options

#### Index expression options

#### Time options

For a list of time modifiers, see Time modifiers for search.

Note: You can also use the earliest and latest attributes to specify absolute and relative time ranges for your search.

For more about this time modifier syntax, see About search time ranges in the Search Manual.

You use the mcatalog command to search metrics data. The metrics data uses a specific format for the metrics fields. See
Metrics data format in Metrics. The _values field is not allowed with this command.

The mcatalog command is a generating command for reports. Generating commands use a leading pipe character. The mcatalog command must be the first command in a search pipeline, except when append=true.

Note: If your role does not have the list_metrics_catalog capability, you cannot use mcatalog.

See About defining roles with capabilities in the Securing Splunk Enterprise manual.

#### WHERE

Use the WHERE clause to filter by supported dimensions.

If you do not specify an index name in the WHERE clause, the mcatalog command returns results from the default metrics indexes associated with your role. If you do not specify an index name and you have no default metrics indexes associated with your role, mcatalog returns no results. To search against all metrics indexes use WHERE index=*.

For more information about defining default metrics indexes for a role in Splunk Enterprise, see Create and manage roles with Splunk Web in Securing Splunk Enterprise.

For more information about defining default metrics indexes for a role in Splunk Cloud Platform, see Create and manage roles with Splunk Web in Securing Splunk Cloud Platform.

#### Group by

You can group by dimension and metric_name fields.

Note: The mcatalog command does not allow grouping by time ranges. The span-length argument is not included in its syntax.

#### Time dimensions

The mcatalog command does not recognize the following time-related dimensions.

#### Lexicographical order

Lexicographical order sorts items based on the values used to encode the items in computer memory. In Splunk software, this is almost always UTF-8 encoding, which is a superset of ASCII.

- Numbers are sorted before letters. Numbers are sorted based on the first digit. For example, the numbers 10, 9, 70, 100 are sorted lexicographically as 10, 100, 70, 9.
- Uppercase letters are sorted before lowercase letters.
- Symbols are not standard. Some symbols are sorted before numeric values. Other symbols are sorted before or after letters.

You can specify a custom sort order that overrides the lexicographical order. See the blog Order Up! Custom Sort Orders.

#### 1. Return all of the metric names in a specific metric index

Return all of the metric names in the new-metric-idx.

#### 2. Return all metric names in the default metric indexes associated with the role of the user

If the user role has no default metric indexes assigned to it, the search returns no events.

#### 3. Return all IP addresses for a specific metric_name among all metric indexes

Return of the IP addresses for the login.failure metric name.

#### 4. Return a list of all available dimensions in the default metric indexes associated with the role of the user

In a distributed search environment, this search is equivalent to | mcatalog values(_dims) WHERE index=default_metric_index.
 