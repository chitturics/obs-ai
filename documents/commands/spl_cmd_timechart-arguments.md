---
 command: timechart-arguments
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Timechart-arguments
 title: timechart-arguments
 download_date: 2026-02-03 09:19:14
---

 ## Syntax
(sep=<string>)? (format=<string>)? (fixedrange=<bool>)? (partial=<bool>)? (cont=<bool>)? (limit=<chart-limit-opt>)? (<stats-agg-term>)? (<bin-options> )* ( <single-agg> | <timechart-single-agg> | ( "(" <eval-expression> ")" ) )+ by <split-by-clause> (<dedup_splitvals>)? sep=<string> format=<string> partial=<bool> count|c|<stats-func>"("<field>|<evaled-field>")" (per_second|per_minute|per_hour|per_day) "(" <field>|<evaled-field> ")" <field> (<tc-option> )* (<where-clause>)? <bin-options>|(usenull=<bool>)|(useother=<bool>)|(nullstr=<string>)|(otherstr=<string>) [+|-] [<time_integer>] <relative_time_unit>@<snap_to_time_unit> where <single-agg> <where-comp> <wherein-comp>|<wherethresh-comp> (in|notin) (top|bottom)<int> (<|>)( )?<num>

## Description
See timechart-command description. Specify the separator to use for output field names when multiple data series are  Specify a parameterized expression with $AGG$ and $VAL$ to construct the output  Controls if partial time buckets should be retained (true) or not (false).  A single aggregation applied to a single field (can be evaled field).  No wildcards are allowed.   Same as single-agg except that additional per_* functions are allowed for computing rates over time Specifies a field to split by.  If field is numerical, default discretization is applied. Timechart options for controlling the behavior of splitting by a field.   In addition to the standard bin-options, the timechart command includes another  Specifies the criteria for including particular data series when a field is given in the tc-by-clause.  A criteria for the where clause. A where-clause criteria that requires the aggregated series value be in or not in some top or bottom grouping. A where-clause criteria that requires the aggregated series value be greater than or less than some numeric threshold.

 