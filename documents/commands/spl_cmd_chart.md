---
 command: chart
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/chart
 title: chart
 download_date: 2026-02-03 09:02:58
---

 # chart

The chart command is a transforming command that returns your results in a table format.  The results can then be used to display the data as a chart, such as a column, line, area, or pie chart. See the  Visualization Reference in the Dashboards and Visualizations manual.

You must specify a statistical function when you use the chart command. See Statistical and charting functions.

The required syntax is in bold.

#### Required arguments

You must include one of the following arguments when you use the chart command.

#### Optional arguments

#### Chart options

#### Stats function options

#### Sparkline options

Sparklines are inline charts that appear within table cells in search results and display time-based trends associated with the primary key of each row.

#### Bin options

The bin options control the number and size of the bins that the search results are separated, or discretized, into.

#### Span options

| Time scale | Syntax | Description |
| --- | --- | --- |
| <sec> | s | sec | secs | second | seconds | Time scale in seconds. |
| <min> | m | min |  mins |  minute |  minutes | Time scale in minutes. |
| <hr> | h | hr |  hrs |  hour | hours | Time scale in hours. |
| <day> | d |  day | days | Time scale in days. |
| <month> | mon | month |  months | Time scale in months. |
| <subseconds> | us | ms |  cs |  ds | Time scale in microseconds (us), milliseconds (ms), centiseconds (cs), or deciseconds (ds) |

#### tc options

The timechart options are part of the <column-split> argument and control the behavior of splitting search results by a field. There are options that control the number and size of the bins that the search results are separated into. There are options that control what happens when events do not contain the split-by field, and for events that do not meet the criteria of the <where-clause>.

#### where clause

The <where-clause> is part of the <column-split> argument.

The chart command is a transforming command. See Command types.

#### Evaluation expressions

You can use the chart command with an eval expression. Unless you specify a split-by clause, the eval expression must be renamed.

#### Supported functions

You can use a wide range of functions with the stats command. For general information about using functions, see  Statistical and charting functions.

- For a list of statistical functions by category, see Function list by category
- For an alphabetical list of statistical functions, see Alphabetical list of functions

#### Functions and memory usage

Some functions are inherently more expensive, from a memory standpoint, than other functions. For example, the distinct_count function requires far more memory than the count function. The values and list functions also can consume a lot of memory.

If you are using the distinct_count function without a split-by field or with a low-cardinality split-by by field, consider replacing the distinct_count function with the the estdc function (estimated distinct count).  The estdc function might result in significantly lower memory usage and run times.

#### Apply a statistical function to all available fields

Some statistical commands, such as stats, process functions that are not paired with one or more fields as if they are implicitly paired with a wildcard, so the command applies the function all available fields. For example, | stats sum is treated as if it is | stats sum(*).

The chart command allows this behavior only with the count function. If you do not specify a field for count, chart applies it to all events returned by the search. If you want to apply other functions to all fields, you must make the wildcard explicit: | chart sum(*) .

#### X-axis

You can specify which field is tracked on the x-axis of the chart. The x-axis variable is specified with a by field and is discretized if necessary. Charted fields are converted to numerical quantities if necessary.

Unlike the timechart command which generates a chart with the _time field as the x-axis, the chart command produces a table with an arbitrary field as the x-axis.

You can also specify the x-axis field after the over keyword, before any by and subsequent split-by clause. The limit and agg options allow easier specification of series filtering. The limit and agg options are ignored if an explicit where-clause is provided.

#### Using row-split and column-split fields

When a column-split field is included, the output is a table where each column represents a distinct value of the column-split field. 
This is in contrast with the stats command, where each row represents a single unique combination of values of the group-by fields. The number of columns included is limited to 10 by default. You can change the number of columns by including a where-clause.

With the chart and timechart commands, you cannot specify the same field in a function and as the row-split field.

For example, you cannot run this search. The field A is specified in the sum function and the row-split argument.

You must specify a different field as in the row-split argument.

Alternatively, you can work around this problem by using an eval expression. For example:

#### Subsecond bin time spans

Subsecond span timescales, which are time spans that are made up of deciseconds (ds), centiseconds (cs), milliseconds (ms), or microseconds (us), should be numbers that divide evenly into a second. For example, 1s = 1000ms. This means that valid millisecond span values are 1, 2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, or 500ms. In addition, span = 1000ms is not allowed. Use span = 1s instead.

#### 1. Chart the max(delay) for each value in a field

Return the maximum delay for each value in the site field.

#### 2. Chart the max(delay) for each value in a field, split by the value of another field

Return the maximum delay for each value in the site field split by the value in the org field.

#### 3. Chart the ratio of the average to the maximum "delay" for each distinct "host" and "user" pair

Return the ratio of the average (mean) of the size field to the maximum "delay" for each distinct host and user pair.

... | chart eval(avg(size)/max(delay)) AS ratio BY host user

#### 4. Chart the maximum "delay" by "size" and separate "size" into bins

Return the maximum value in the delay field by the size field, where size is broken down into a maximum of 10 equal sized bins.

#### 5. Chart the average size for each distinct value in a filed

Return the average (mean) value in the size field for each distinct value in the host field.

#### 6. Chart the number of events, grouped by date and hour

Return the number of events, grouped by date and hour of the day, using span to group per 7 days and 24 hours per half days. The span applies to the field immediately prior to the command.

... | chart count BY date_mday span=3 date_hour span=12

#### 7. Align the chart time bins to local time

Align the time bins to 5am (local time).  Set the span to 12h. The bins will represent 5am - 5pm, then 5pm - 5am (the next day), and so on.

#### 8. In a multivalue BY field, remove duplicate values

For each unique value of mvfield, chart the average value of field. Deduplicates the values in the mvfield.

...| chart avg(field) BY mvfield dedup_splitval=true

#### 1. Specify <row-split> and <column-split> values with the chart command

This example uses events that list the numeric sales for each product and quarter, for example:

| products | quarter | sales |
| --- | --- | --- |
| ProductA | QTR1 | 1200 |
| ProductB | QTR1 | 1400 |
| ProductC | QTR1 | 1650 |
| ProductA | QTR2 | 1425 |
| ProductB | QTR2 | 1175 |
| ProductC | QTR2 | 1550 |
| ProductA | QTR3 | 1300 |
| ProductB | QTR3 | 1250 |
| ProductC | QTR3 | 1375 |
| ProductA | QTR4 | 1550 |
| ProductB | QTR4 | 1700 |
| ProductC | QTR4 | 1625 |

To summarize the data by product for each quarter, run this search:

source="addtotalsData.csv" | chart sum(sales) BY products quarter

In this example, there are two fields specified in the BY clause with the chart command.

- The products field is referred to as the <row-split> field. In the chart, this field forms the X-axis.
- The quarter field is referred to as the <column-split> field. In the chart, this field forms the data series.

The results appear on the Statistics tab and look something like this:

| products | QTR1 | QTR2 | QTR3 | QTR4 |
| --- | --- | --- | --- | --- |
| ProductA | 1200 | 1425 | 1300 | 1550 |
| ProductB | 1400 | 1175 | 1250 | 1700 |
| ProductC | 1650 | 1550 | 1375 | 1625 |

Click on the Visualization tab to see the results as a chart.

See the addtotals command for an example that adds a total column for each product.

#### 2. Chart the number of different page requests for each Web server

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Chart the number of different page requests, GET and POST, that occurred for each Web server.

sourcetype=access_* | chart count(eval(method="GET")) AS GET, count(eval(method="POST")) AS POST by host

This example uses eval expressions to specify the different field values for the stats command to count. The first clause uses the count() function to count the Web access events that contain the method field value GET. Then, using the AS keyword,  the field that represents these results is renamed GET.

The second clause does the same for POST events. The counts of both types of events are then separated by the web server, using the BY clause with the host field.

The results appear on the Statistics tab and look  like this:

| host | GET | POST |
| --- | --- | --- |
| www1 | 8431 | 5197 |
| www2 | 8097 | 4815 |
| www3 | 8338 | 4654 |

Click the Visualization tab. If necessary, format the results as a column chart. This chart displays the total count of events for each event type, GET or POST, based on the host value.

#### 3. Chart the number of transactions by duration

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Create a chart to show the number of transactions based on their duration (in seconds).

sourcetype=access_* status=200 action=purchase | transaction clientip maxspan=10m | chart count BY duration span=log2

This search uses the transaction command to define a transaction as events that share the clientip field and fit within a ten minute time span. The transaction command creates a new field called duration, which is the difference between the timestamps for the first and last events in the transaction. (Because maxspan=10s, the duration value should not be greater than this.)

The transactions are then piped into the chart command. The count() function is used to count the number of transactions and separate the count by the duration of each transaction. Because the duration is in seconds and you expect there to be many values, the search uses the span argument to bucket the duration into bins of log2 (span=log2).

The results appear on the Statistics tab and look something like this:

| duration | count |
| --- | --- |
| 0 | 970 |
| 1-2 | 593 |
| 2-4 | 208 |
| 4-8 | 173 |
| 8-16 | 26 |
| 64-128 | 3 |
| 128-256 | 3 |
| 256-512 | 12 |
| 512-1024 | 2 |

#### 4. Chart the average number of events in a transaction, based on transaction duration

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Create a chart to show the average number of events in a transaction based on the duration of the transaction.

sourcetype=access_* status=200 action=purchase | transaction clientip maxspan=30m  | chart avg(eventcount) by duration span=log2

The transaction command adds two fields to the results duration and eventcount. The eventcount field tracks the number of events in a single transaction.

In this search, the transactions are piped into the chart command. The avg() function is used to calculate the average number of events for each duration. Because the duration is in seconds and you expect there to be many values, the search uses the span argument to bucket the duration into bins using logarithm with a base of 2.

Use the field format option to enable number formatting.

#### 5. Chart customer purchases

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Chart how many different people bought something and what they bought at the Buttercup Games online store Yesterday.

This search takes the purchase events and pipes it into the chart command. The dc() or distinct_count() function is used to count the number of unique visitors (characterized by the clientip field). This number is then charted over each hour of the day and broken out based on the category_id of the purchase. Also, because these are numeric values, the search uses the usenull=f argument to exclude fields that don't have a value.

The results appear on the Statistics tab and look something like this:

| date_hour | ACCESSORIES | ARCADE | SHOOTER | SIMULATION | SPORTS | STRATEGY | TEE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2 | 6 | 0 | 4 | 0 | 4 | 4 |
| 1 | 4 | 7 | 2 | 3 | 0 | 10 | 5 |
| 2 | 2 | 2 | 2 | 1 | 1 | 2 | 0 |
| 3 | 3 | 5 | 3 | 5 | 0 | 7 | 1 |
| 4 | 3 | 4 | 0 | 0 | 1 | 4 | 0 |
| 5 | 3 | 0 | 3 | 0 | 1 | 6 | 1 |

Each line represents a different type of product that is sold at the Buttercup Games online store. The height of each line shows the number of different people who bought the product during that hour. In general, it looks like the most popular items at the online shop were Arcade games.

You can format the report as a stacked column chart, which will show you the total purchases at each hour of day.

- Change the chart type to a Column Chart.
- Use the Format menu, and on the General tab select stacked.

#### 6. Chart the number of earthquakes and the magnitude of each earthquake

| This example uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and add it as an input. |

Create a chart that list the number of earthquakes, and the magnitude of each earthquake that occurred in and around Alaska.  Run the search using the time range All time.

source=all_month.csv place=*alaska* mag>=3.5 | chart count BY mag place useother=f | rename mag AS Magnitude

This search counts the number of earthquakes that occurred in the Alaska regions. The count is then broken down for each place based on the magnitude of the quake. Because the place value is non-numeric, the search uses the useother=f argument to exclude events that don't match.

The results appear on the Statistics tab and look something like this:

| Magnitude | 145km ENE of Chirikof Island, Alaska | 225km SE of Kodiak, Alaska | 250km SE of Kodiak, Alaska | 252km SE of Kodiak, Alaska | 254km SE of Kodiak, Alaska | 255km SE of Kodiak, Alaska | 259km SE of Kodiak, Alaska | 264km SE of Kodiak, Alaska | 265km SE of Kodiak, Alaska | Gulf of Alaska |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3.5 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 2 | 2 |
| 3.6 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| 3.7 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| 3.8 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 3 |
| 3.9 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| 4 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 1 |
| 4.1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 4.2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| 4.3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 4.4 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| 4.6 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
 