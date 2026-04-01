---
 command: timechart
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/timechart
 title: timechart
 download_date: 2026-02-03 09:19:05
---

 # timechart

Creates a time series chart with corresponding table of statistics.

A timechart is a statistical aggregation applied to a field to produce a chart, with time used as the X-axis. You can specify a split-by field, where each distinct value of the split-by field becomes a series in the chart. If you use an eval expression, the split-by clause is required. With the limit and agg options, you can specify series filtering. These options are ignored if you specify an explicit where-clause. If you set limit=0, no series filtering occurs.

The required syntax is in bold.

#### Required arguments

When specifying timechart command arguments, either <single-agg> or <eval-expression> BY <split-by-clause> is required.

#### Optional arguments

#### Stats function options

#### Bin options

#### Span options

#### tc options

The <tc-option> is part of the <split-by-clause>.

#### where clause

The <where-clause> is part of the <split-by-clause>. The <where-clause> is comprised of two parts, a single aggregation and some options. See Where clause examples.

The timechart command is a transforming command. See Command types.

Note: Do not run searches that modify the _time field using eval and timechart commands with the span argument. The _time field is an internal field that should not be overwritten. See Use default fieldsUse default fields.

#### bins and span arguments

The timechart command accepts either the bins argument OR the span argument. If you specify both bins and span, span is used. The bins argument is ignored.

If you do not specify either bins or span, the timechart command uses the default bins=100.

#### Default time spans

If you use the predefined time ranges in the time range picker, and do not specify the span argument, the following table shows the default span that is used.

| Time range | Default span |
| --- | --- |
| Last 15 minutes | 10 seconds |
| Last 60 minutes | 1 minute |
| Last 4 hours | 5 minutes |
| Last 24 hours | 30 minutes |
| Last 7 days | 1 day |
| Last 30 days | 1 day |
| Previous year | 1 month |

(Thanks to Splunk users MuS and Martin Mueller for their help in compiling this default time span information.)

#### Spans used when minspan is specified

When you specify a minspan value, the span that is used for the search must be equal to or greater than one of the span threshold values in the following table. For example, if you specify minspan=15m that is equivalent to 900 seconds. The minimum span that can be used is 1800 seconds, or 30 minutes.

| Span threshold | Time equivalents |
| --- | --- |
| 1 second |  |
| 5 seconds |  |
| 10 seconds |  |
| 30 seconds |  |
| 60 seconds | 1 minute |
| 300 seconds | 5 minutes |
| 600 seconds | 10 minutes |
| 1800 seconds | 30 minutes |
| 3600 seconds | 1 hour |
| 86400 seconds | 1 day |
| 2592000 seconds | 30 days |

#### Bin time spans and local time

The span argument always rounds down the starting date for the first bin. There is no guarantee that the bin start time used by the timechart command corresponds to your local timezone. In part this is due to differences in daylight savings time for different locales. To use day boundaries, use span=1d. Do not use not span=86400s, or span=1440m, or span=24h.

#### Bin time spans versus per_* functions

The functions, per_day(), per_hour(), per_minute(), and per_second() are aggregator functions and are not responsible for setting a time span for the resultant chart. These functions are used to get a consistent scale for the data when an explicit span is not provided. The resulting span can depend on the search time range.

For example, per_hour() converts the field value so that it is a rate per hour, or sum()/<hours in the span>. If your chart span ends up being 30m, it is sum()*2.

If you want the span to be 1h, you still have to specify the argument span=1h in your search.

Note: You can do per_hour() on one field and per_minute() (or any combination of the functions) on a different field in the same search.

#### Subsecond bin time spans

Subsecond span timescales, which are time spans that are made up of deciseconds (ds), centiseconds (cs), milliseconds (ms), or microseconds (us), should be numbers that divide evenly into a second. For example, 1s = 1000ms. This means that valid millisecond span values are 1, 2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, or 500ms. In addition, span = 1000ms is not allowed. Use span = 1s instead.

#### Split-by fields

If you specify a split-by field, ensure that you specify the bins and span arguments before the split-by field. If you specify these arguments after the split-by field, Splunk software assumes that you want to control the bins on the split-by field, not on the time axis.

If you use chart or timechart, you cannot use a field that you specify in a function as your split-by field as well. For example, you will not be able to run:

However, you can work around this with an eval expression, for example:

#### Prepending VALUE to the names of some fields that begin with underscore (  _  )

In timechart searches that include a split-by-clause, when search results include a field name that begins with a leading underscore (  _  ), Splunk software prepends the field name with VALUE and creates as many columns as there are unique entries in the argument of the BY clause. Prepending the string with VALUE distinguishes the field from internal fields and avoids naming a column with a leading underscore, which ensures that the field is not hidden in the output schema like most internal fields.

For example, consider the following search:

The results look something like this:

| _time | VALUE_audit | VALUE_internal |
| --- | --- | --- |
| 2023-06-26 21:00:00 | 1 | 586 |
| 2023-06-26 21:01:00 | 1 | 295 |
| 2023-06-26 21:02:00 | 1 | 555 |

The columns are displayed in the search results as VALUE_audit and VALUE_internal.

#### Supported functions

You can use a wide range of functions with the timechart command. For general information about using functions, see Statistical and charting functions.

- For a list of functions by category, see Function list by category
- For an alphabetical list of functions, see Alphabetical list of functions

#### Functions and memory usage

Some functions are inherently more expensive, from a memory standpoint, than other functions. For example, the distinct_count function requires far more memory than the count function. The values and list functions also can consume a lot of memory.

If you are using the distinct_count function without a split-by field or with a low-cardinality split-by by field, consider replacing the distinct_count function with the the estdc function (estimated distinct count). The estdc function might result in significantly lower memory usage and run times.

#### Lexicographical order

Lexicographical order sorts items based on the values used to encode the items in computer memory. In Splunk software, this is almost always UTF-8 encoding, which is a superset of ASCII.

- Numbers are sorted before letters. Numbers are sorted based on the first digit. For example, the numbers 10, 9, 70, 100 are sorted lexicographically as 10, 100, 70, 9.
- Uppercase letters are sorted before lowercase letters.
- Symbols are not standard. Some symbols are sorted before numeric values. Other symbols are sorted before or after letters.

You can specify a custom sort order that overrides the lexicographical order. See the blog Order Up! Custom Sort Orders.

#### 1. Chart the product of the average "CPU" and average "MEM" for each "host"

For each minute, compute the product of the average "CPU" and average "MEM" for each "host".

#### 2. Chart the average of cpu_seconds by processor

This example uses an eval expression that includes a statistical function, avg to calculate the average of cpu_seconds field, rounded to 2 decimal places. The results are organized by the values in the processor field. When you use a eval expression with the timechart  command, you must also use  BY clause.

#### 3. Chart the average of "CPU" for each "host"

For each minute, calculate the average value of "CPU" for each "host".

#### 4. Chart the average "cpu_seconds" by "host" and remove outlier values

Calculate the average "cpu_seconds" by "host". Remove outlying values that might distort the timechart axis.

#### 5. Chart the average "thruput" of hosts over time

#### 6. Chart the eventypes by source_ip

For each minute, count the eventypes by source_ip, where the count is greater than 10.

#### 7. Align the chart time bins to local time

Align the time bins to 5am (local time).  Set the span to 12h. The bins will represent 5am - 5pm, then 5pm - 5am (the next day), and so on.

#### 8. In a multivalue BY field, remove duplicate values

For each unique value of mvfield, return the average value of field. Deduplicates the values in the mvfield.

#### 9. Rename fields prepended with VALUE

To rename fields with leading underscores that are prepended with VALUE, add the following command to your search:

The columns in your search results now display without the leading VALUE_ in the field name.

#### 1. Chart revenue for the different products

| This example uses the sample dataset from the Search Tutorial and a field lookup to add more information to the event data. To try this example for yourself:
Download the tutorialdata.zip file from this topic in the Search Tutorial and follow the instructions to upload the file to your Splunk deployment.Download the Prices.csv.zip file from this topic in the Search Tutorial and follow the instructions to set up your field lookup.Use the time range Yesterday when you run the search.
The tutorialdata.zip file includes a productId field that is the catalog number for the items sold at the Buttercup Games online store. The field lookup uses the prices.csv file to add two new fields to your events: productName, which is a descriptive name for the item, and price, which is the cost of the item. |

Chart the revenue for the different products that were purchased yesterday.

- This example searches for all purchase events (defined by the action=purchase).
- The results are piped into timechart command.
- The per_hour() function sums up the values of the price field for each productName and organizes the total by time.

This search produces the following table of results in the Statistics tab. To format the numbers to the proper digits for currency, click the format icon in the column heading. On the Number Formatting tab, select the Precision.

After you create this chart, you can position your mouse pointer over each section to view more metrics for the product purchased at that hour of the day.

Notice that the chart does not display the data in hourly spans. Because a span is not provided (such as span=1hr), the per_hour() function converts the value so that it is a sum per hours in the time range (which in this example is 24 hours).

#### 2. Chart daily purchases by product type

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Chart the number of purchases made daily for each type of product.

- This example searches for all purchases events, defined by the action=purchase, and pipes those results into the timechart command.
- The span=1day argument buckets the count of purchases over the week into daily chunks.
- The usenull=f argument ignore any events that contain a NULL value for categoryId.

The results appear on the Statistics tab and look something like this:

| _time | ACCESSORIES | ARCADE | SHOOTER | SIMULATION | SPORTS | STRATEGY | TEE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2018-03-29 | 5 | 17 | 6 | 3 | 5 | 32 | 9 |
| 2018-03-30 | 62 | 63 | 39 | 30 | 22 | 127 | 56 |
| 2018-03-31 | 65 | 94 | 38 | 42 | 34 | 128 | 60 |
| 2018-04-01 | 54 | 82 | 42 | 39 | 13 | 115 | 66 |
| 2018-04-02 | 52 | 63 | 45 | 42 | 22 | 124 | 52 |
| 2018-04-03 | 46 | 76 | 34 | 42 | 19 | 123 | 59 |
| 2018-04-04 | 57 | 70 | 36 | 38 | 20 | 130 | 56 |
| 2018-04-05 | 46 | 72 | 35 | 37 | 13 | 106 | 46 |

Click the Visualization tab. If necessary, change the chart to a column chart.

Compare the number of different items purchased each day and over the course of the week.

#### 3. Display results in 1 week intervals

| This search uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance.  This example uses the All Earthquakes data from  the past 30 days. |

This search counts the number of earthquakes in Alaska where the magnitude is greater than or equal to 3.5.  The results are organized in spans of 1 week, where the week begins on Monday.

- The <by-clause> is used to group the earthquakes by magnitude.
- You can only use week spans with the snap-to span argument in the timechart command.  For more information, see Specify a snap to time unit.

The results appear on the Statistics tab and look something like this:

| _time | 3.5 | 3.6 | 3.7 | 3.8 | 4 | 4.1 | 4.1 | 4.3 | 4.4 | 4.5 | OTHER |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2018-03-26 | 3 | 3 | 2 | 2 | 3 | 1 | 0 | 2 | 1 | 1 | 1 |
| 2018-04-02 | 5 | 7 | 2 | 0 | 3 | 2 | 1 | 0 | 0 | 1 | 1 |
| 2018-04-09 | 2 | 3 | 1 | 2 | 0 | 2 | 1 | 1 | 0 | 1 | 2 |
| 2018-04-16 | 6 | 5 | 0 | 1 | 2 | 2 | 2 | 0 | 0 | 2 | 1 |
| 2018-04-23 | 2 | 0 | 0 | 0 | 0 | 2 | 1 | 2 | 2 | 0 | 1 |

#### 4. Count the revenue for each item over time

| This example uses the sample dataset from the Search Tutorial and a field lookup to add more information to the event data. Before you run this example:
Download the data set from this topic in the Search Tutorial and follow the instructions to upload it to your Splunk deployment.Download the Prices.csv.zip file from this topic in the Search Tutorial and follow the instructions to set up your field lookup.
The original data set includes a productId field that is the catalog number for the items sold at the Buttercup Games online store. The field lookup adds two new fields to your events: productName, which is a descriptive name for the item, and price, which is the cost of the item. |

Count the total revenue made for each item sold at the shop over the last 7 days. This example shows two different searches to generate the calculations.

Both searches produce similar results. Search 1 produces values with two decimal places.  Search 2 produces values with six decimal places.  The following image shows the results from Search 1.

Click the Visualization tab. If necessary, change the chart to a column chart.

#### 5. Chart product views and purchases for a single day

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Chart a single day's views and purchases at the Buttercup Games online store.

- This search uses the per_hour() function and eval expressions to search for page views (method=GET) and purchases (action=purchase).
- The results of the eval expressions are renamed as Views and Purchases, respectively.

The results appear on the Statistics tab and look something like this:

| _time | Views | Purchases |
| --- | --- | --- |
| 2018-04-05 00:00:00 | 150.000000 | 44.000000 |
| 2018-04-05 00:30:00 | 166.000000 | 54.000000 |
| 2018-04-05 01:00:00 | 214.000000 | 72.000000 |
| 2018-04-05 01:30:00 | 242.000000 | 80.000000 |
| 2018-04-05 02:00:00 | 158.000000 | 26.000000 |
| 2018-04-05 02:30:00 | 166.000000 | 20.000000 |
| 2018-04-05 03:00:00 | 220.000000 | 56.000000 |

These examples use the where clause to control the number of series values returned in the time-series chart.

Example 1: Show the 5 most rare series based on the minimum count values. All other series values will be labeled as "other".

These two searches return six data series: the five top or bottom series specified and the series labeled other. To hide the "other" series, specify the argument useother=f.

The following two searches returns the sources series with a total count of events greater than 100. All other series values will be labeled as "other".
 