---
 command: mstats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/mstats
 title: mstats
 download_date: 2026-02-03 09:12:04
---

 # mstats

Use the mstats command to analyze metrics. This command performs statistics on the measurement, metric_name, and dimension fields in metric indexes. You can use mstats in historical searches and real-time searches. When you use mstats in a real-time search with a time window, a historical search runs first to backfill the data.

Note: The mstats command provides the best search performance when you use it to search a single metric_name value or a small number of metric_name values.

Note: Certain restricted search commands, including mpreview, mstats, tstats, typeahead, and walklex, might stop working if your organization uses field filters to protect sensitive data. See Plan for field filters in your organization in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Stats metric term options

For an overview of using functions with commands, see Statistical and charting functions.

#### Chart options

#### Logical expression options

#### Comparison expression options

#### Search modifier options

#### Span length options

- Manage Splunk Cloud Platform indexes in the Splunk Cloud Platform Admin Manual if you use Splunk Cloud Platform.
- Create custom indexes in Managing indexers and clusters of indexers if you use Splunk Enterprise.

#### Time options

The mstats command is a report-generating command, except when append=true. See Command types.

Generating commands use a leading pipe character and should be the first command in a search, except when  append=true is specified with the command.

Use the mstats command to search metrics data. The metrics data uses a specific format for the metrics fields. See Metrics data format in Metrics.

Note: All metrics search commands are case sensitive. This means, for example, that mstats treats as the following as three distinct values of metric_name: cap.gear, CAP.GEAR, and Cap.Gear.

mstats searches cannot return results for metric data points with metric_name fields that are empty or which contain blank spaces.

#### Append mstats searches together

The mstats command does not support subsearches. You can use the append argument to add the results of an mstats search to the results of a preceding mstats search. See the topic on the tstats command for an append usage example.

#### Aggregations

If you are using the <stats-func> syntax, numeric aggregations are only allowed on specific values of the metric_name field. The metric name must be enclosed in parenthesis. If there is no data for the specified metric_name in parenthesis, the search is still valid.

If you are using the <stats-func-value> syntax, numeric aggregations are only allowed on the _value field.

Aggregations are not allowed for values of any other field, including the _time field.

Note: When prestats = true and you run an mstats search that uses the c and count aggregation functions without an aggregation field, the Splunk software processes them as if they are actually count(_value). In addition, any statistical functions that follow in the search string must reference the _value field. For example: | mstats count | timechart count(_value)

#### Wildcard characters

The mstats command supports wildcard characters in any search filter, with the following exceptions:

- You cannot use wildcard characters in the GROUP BY clause.
- If you are using the <stats_func_value> syntax, you cannot use wildcard characters in the _value field.
- If you are using wildcard characters in your aggregations and you are renaming them, your rename must have matching wildcards.

- Real-time mstats searches cannot utilize wildcarded metric aggregations when you use the <stats-func> syntax.

#### WHERE clause

Use the WHERE clause to filter by any of the supported dimensions.

If you are using the <stats-func> syntax, the WHERE clause cannot filter by metric_name. Filtering by metric_name is performed based on the metric_name fields specified with the <stats-func> argument.

If you are using the <stats-func-value> syntax, the WHERE clause must filter by metric_name.

The WHERE clause is case-sensitive when it filters mstats results by field values. For example, these two searches return different result sets:

- | mstats max(df.used) as "Disk Utilization" WHERE (itsi_entity_type_nix_metrics_indexes) AND host=test
- | mstats max(df.used) as "Disk Utilization" WHERE (itsi_entity_type_nix_metrics_indexes) AND host=Test

If you do not specify an index name in the WHERE clause, the mstats command returns results from the default metrics indexes associated with your role. If you do not specify an index name and you have no default metrics indexes associated with your role, mstats returns no results. To search against all metrics indexes use WHERE index=*.

The WHERE clause must come before the BY or GROUPBY clause, if they are both used in conjunction with mstats.

For more information about defining default metrics indexes for a role, see Add and edit roles with Splunk Web in Securing Splunk Enterprise.

#### Group results by metric name and dimension

You can group results by the metric_name and dimension fields.

You can also group by time. You must specify a timespan using the <span-length> argument to group by time buckets. For example, span=1hr or span=auto.  The <span-length> argument is separate from the BY clause and can be placed at any point in the search between clauses.

Grouping by the _value or _time fields is not allowed.

#### Group by metric time series

You can group results by metric time series. A metric time series is a set of metric data points that share the same metrics and the same dimension field-value pairs. Grouping by metric time series ensures that you are not mixing up data points from different metric data sources when you perform statistical calculations on them.

Use BY _timeseries to group by metric time series. The _timeseries field is internal and won't display in your results. If you want to display the _timeseries values in your search, add | rename _timeseries AS timeseries to the search.

For a detailed overview of the _timeseries field with examples, see Perform statistical calculations on metric time series in Metrics.

#### Time dimensions

The mstats command does not recognize the following time-related dimensions.

#### Subsecond bin time spans

You can only use subsecond span timescales, which are time spans that are made up of deciseconds (ds), centiseconds (cs), milliseconds (ms), or microseconds (us), for mstats searches over metrics indexes that have been configured to have millisecond timestamp resolution.

Subsecond span timescales should be numbers that divide evenly into a second. For example, 1s = 1000ms. This means that valid millisecond span values are 1, 2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, or 500ms. In addition, span = 1000ms is not allowed. Use span = 1s instead.

For more information about giving indexes millisecond timestamp resolution:

- For Splunk Cloud Platform: See Manage Splunk Cloud Platform indexes in the Splunk Cloud Platform Admin Manual.
- For Splunk Enterprise: See Create custom indexes in Managing indexes and clusters of indexes.

#### Search over a set of indexes with varying levels of timestamp resolution

If you run an mstats search over multiple metrics indexes with varying levels of timestamp resolution, the results of the search may contain results with timestamps of different resolutions.

For example, say you have two metrics indexes. Your "metrics-second" metrics index has a second timestamp resolution. Your "metrics-ms" metrics index has a millisecond timestamp resolution. You run the following search over both indexes: | mstats count(*) WHERE index=metric* span=100ms.

The search produces the following results:

| _time | count(cpu.nice) |
| --- | --- |
| 1549496110 | 48 |
| 1549496110.100 | 2 |

The  11549496110 row counts results from both indexes. The count from "metric-ms" includes only metric data points with timestamps from 1549496110.000 to 1549496110.099. The "metric-ms" metric data points with timestamps from 1549496110.100 to 1549496110.199 appear in the 1549496110.100 row.

Meanwhile, the metric data points in the "metric-second" index do not have millisecond timestamp precision. The 1549496110 row only counts those "metric-second" metric data points with the 11549496110 timestamp, and no metric data points from "metric-second" are counted in the 1549496110.100 row.

#### Time bin limits for mstats search jobs

Splunk software regulates mstats search jobs that use span or a similar method to group results by time. When Splunk software processes these jobs, it limits the number of "time bins" that can be allocated within a single .tsidx file.

For metrics indexes with second timestamp resolution, this only affects searches with large time ranges and very small time spans, such as a search over a year with span = 1s. If you are searching on a metrics index with millisecond timestamp resolution, you might encounter this limit over shorter ranges, such as a search over an hour with span = 1ms.

This limit is set by time_bin_limit in limits.conf, which is set to 1 million bins by default. If you need to run these kinds of mstats search jobs, lower this value if they are using too much memory per search. Raise this value if these kinds of search jobs are returning errors.

The Splunk platform estimates the number of time bins that a search requires by dividing the search time range by its group-by span. If this produces a number that is larger than the time_bin_limit, the Splunk platform returns an error.

The search time range is determined by the earliest and latest values of the search. Some kinds of searches, such as all-time searches, do not have earliest and latest. In such cases the Splunk platform checks within each single TSIDX file to derive a time range for the search.

Note: Metrics indexes have second timestamp resolution by default. You can give a metrics index a millisecond timestamp resolution when you create it, or you can edit an existing metrics index to switch it to millisecond timestamp resolution.

If you use Splunk Cloud, see Manage Splunk Cloud Platform indexes in the Splunk Cloud Platform Admin Manual. 
If you use Splunk Enterprise, see Create custom indexes in Managing indexes and clusters of indexes.

#### Memory and mstats search performance

A pair of limits.conf settings strike a balance between the performance of mstats searches and the amount of memory they use during the search process, in RAM and on disk. If your mstats searches are consistently slow to complete you can adjust these settings to improve their performance, but at the cost of increased search-time memory usage, which can lead to search failures.

If you use Splunk Cloud Platform, you will need to file a Support ticket to change these settings.

For more information, see Memory and stats search performance in the Search Manual.

#### Lexicographical order

Lexicographical order sorts items based on the values used to encode the items in computer memory. In Splunk software, this is almost always UTF-8 encoding, which is a superset of ASCII.

- Numbers are sorted before letters. Numbers are sorted based on the first digit. For example, the numbers 10, 9, 70, 100 are sorted lexicographically as 10, 100, 70, 9.
- Uppercase letters are sorted before lowercase letters.
- Symbols are not standard. Some symbols are sorted before numeric values. Other symbols are sorted before or after letters.

You can specify a custom sort order that overrides the lexicographical order. See the blog Order Up! Custom Sort Orders.

#### 1. Calculate a single metric grouped by time

Return the average value of the aws.ec2.CPUUtilization metric in the mymetricdata metric index. Bucket the results into 30 second time spans.

| mstats avg(aws.ec2.CPUUtilization) WHERE index=mymetricdata span=30s

#### 2. Combine metrics with different metric names

Return the average value of both the aws.ec2.CPUUtilization metric and the os.cpu.utilization metric. Group the results by host and bucket the results into 1 minute time spans.  Both metrics are combined and considered a single metric series.

| mstats avg(aws.ec2.CPUUtilization) avg(os.cpu.utilization) WHERE index=mymetricdata BY host span=1m

#### 3. Use chart=t mode to chart metric event counts by the top ten hosts

Return a chart of the number of aws.ec2.CPUUtilization metric data points for each day, split by the top ten hosts.

| mstats chart=t count(aws.ec2.CPUUtilization) WHERE index=mymetricdata by host span=1d chart.limit=top10

#### 4. Filter the results on a dimension value and split by the values of another dimension

Return the average value of the aws.ec2.CPUUtilization metric for all measurements with host=www2 and split the results by the values of the app dimension.

| mstats avg(aws.ec2.CPUUtilization) WHERE host=www2 BY app

#### 5. Specify multiple aggregations of multiple metrics

Return the average and maximum of the resident set size and virtual memory size. Group the results by metric_name and bucket them into 1 minute spans

| mstats avg(os.mem.rss) AS "AverageRSS" max(os.mem.rss) AS "MaxRSS" avg(os.mem.vsz) AS "AverageVMS" max(os.mem.vsz) AS "MaxVMS" WHERE index=mymetricdata BY metric_name span=1m

#### 6. Aggregate a metric across all of your default metrics indexes, using downsampling to speed up the search

Find the median of the aws.ec2.CPUUtilization metric. Do not include an index filter to search for measurements in all of the default metrics indexes associated with your role. Speed up the search by using every to compute the median for one minute of every five minutes covered by the search.

| mstats median(aws.ec2.CPUUtilization) span=1m every=5m

#### 7. Get the rate of an accumulating counter metric and group the results by time series

See Perform statistical calculations on metric time series in Metrics for more information.

| mstats rate(spl.intr.resource_usage.PerProcess.data.elapsed) as data.elapsed where index=_metrics BY _timeseries | rename _timeseries AS timeseries

#### 8. Stats-func-value example

Use the <stats-func-value> syntax to get a count of all of the measurements for the aws.ec2.CPUUtilization metric in the mymetricdata index.

| mstats count(_value) WHERE metric_name=aws.ec2.CPUUtilization AND index=mymetricdata
 