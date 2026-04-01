---
 command: fieldsummary
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/fieldsummary
 title: fieldsummary
 download_date: 2026-02-03 09:06:47
---

 # fieldsummary

The fieldsummary command calculates summary statistics for all fields or a subset of the fields in your events. The summary information is displayed as a results table.

fieldsummary [maxvals=<unsigned_int>] [<wc-field-list>]

#### Optional arguments

The fieldsummary command is a dataset processing command. See Command types.

The fieldsummary command displays the summary information in a results table. The following information appears in the results table:

| Summary field name | Description |
| --- | --- |
| field | The field name in the event. |
| count | The number of events/results with that field. |
| distinct_count | The number of unique values in the field. |
| is_exact | Whether or not the field is exact. This is related to the distinct count of the field values.  If the number of values of the field exceeds maxvals, then fieldsummary will stop retaining all the values and compute an approximate distinct count instead of an exact one. 1 means it is exact, 0 means it is not. |
| max | If the field is numeric, the maximum of its value. |
| mean | If the field is numeric, the mean of its values. |
| min | If the field is numeric, the minimum of its values. |
| numeric_count | The count of numeric values in the field. This would not include NULL values. |
| stdev | If the field is numeric, the standard deviation of its values. |
| values | The distinct values of the field and count of each value. The values are sorted first by highest count and then by distinct value, in ascending order. |

#### 1. Return summaries for all fields

This example returns summaries for all fields in the _internal index from the last 15 minutes.

index=_internal earliest=-15m latest=now | fieldsummary

In this example, the results in the max, min, and stdev fields are formatted to display up to 4 decimal points.

#### 2. Return summaries for specific fields

This example returns summaries for fields in the _internal index with names that contain "size" and "count". The search returns only the top 10 values for each field from the last 15 minutes.

index=_internal earliest=-15m latest=now | fieldsummary maxvals=10 *size* *count*

analyzefields, 
anomalies,
anomalousvalue,
stats
 