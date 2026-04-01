---
 command: stats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/stats
 title: stats
 download_date: 2026-02-03 09:17:53
---

 # stats

Calculates aggregate statistics, such as average, count, and sum, over the results set. This is similar to SQL aggregation.
If the stats command is used without a BY clause, only one row is returned, which is the aggregation over the entire incoming result set. If a BY clause is used, one row is returned for each distinct value specified in the BY clause.

The stats command can be used for several SQL-like operations. If you are familiar with SQL but new to SPL, see  Splunk SPL for SQL users.

#### Difference between stats and eval commands

The stats command calculates statistics based on fields in your events.  The eval command creates new fields in your events by using existing fields and an arbitrary expression.

#### Required arguments

#### Optional arguments

#### Stats function options

#### Sparkline function options

Sparklines are inline charts that appear within table cells in search results to display time-based trends associated with the primary key of each row. Read more about how to "Add sparklines to your search results" in the Search Manual.

The stats command is a transforming command. See Command types.

#### Eval expressions with statistical functions

When you use the stats command, you must specify either a statistical function or a sparkline function. When you use a statistical function, you can use an eval expression as part of the statistical function. For example:

#### Statistical functions that are not applied to specific fields

With the exception of the count function, when you pair the stats command with functions that are not applied to specific fields or eval expressions that resolve into fields, the search head processes it as if it were applied to a wildcard for all fields. In other words, when you have | stats avg in a search, it returns results for | stats avg(*).

This "implicit wildcard" syntax is officially deprecated, however. Make the wildcard explicit. Write | stats <function>(*) when you want a function to apply to all possible fields.

#### Numeric calculations

During calculations, numbers are treated as double-precision floating-point numbers, subject to all the usual behaviors of floating point numbers. If the calculation results in the floating-point special value NaN, it is represented as "nan" in your results. The special values for positive and negative infinity are represented in your results as "inf" and "-inf" respectively. Division by zero results in a null field.

There are situations where the results of a calculation contain more digits than can be represented by a floating- point number. In those situations precision might be lost on the least significant digits. For an example of how to correct this, see Example 2 of the  basic examples for the sigfig(X) function.

#### Ensure correct search behavior when time fields are missing from input data

Ideally, when you run a stats search that aggregates results on a time function such as latest(), latest_time(), or rate(), the search should not return results when _time or _origtime fields are missing from the input data. However, searches that fit this description return results by default, which means that those results might be incorrect or random.

Correct this behavior by changing the check_for_invalid_time setting in limits.conf file.

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local.
- Under the [stats] stanza, set check_for_invalid_time to true.

When you set check_for_invalid_time=true, the stats search processor does not return results for searches on time functions when the input data does not include the _time or _origtime fields.

#### Functions and memory usage

Some functions are inherently more expensive, from a memory standpoint, than other functions. For example, the distinct_count function requires far more memory than the count function. The values and list functions also can consume a lot of memory.

If you are using the distinct_count function without a split-by field or with a low-cardinality split-by by field, consider replacing the distinct_count function with the the estdc function (estimated distinct count).  The estdc function might result in significantly lower memory usage and run times.

#### Memory and stats search performance

A pair of limits.conf settings strike a balance between the performance of stats searches and the amount of memory they use during the search process, in RAM and on disk. If your stats searches are consistently slow to complete you can adjust these settings to improve their performance, but at the cost of increased search-time memory usage, which can lead to search failures.

If you use Splunk Cloud Platform, you need to file a Support ticket to change these settings.

For more information, see Memory and stats search performance in the Search Manual.

#### Event order functions

Using the first and last functions when searching based on time does not produce accurate results.

- To locate the first value based on time order, use the earliest function, instead of the first function.
- To locate the last value based on time order, use the latest function, instead of the last function.

For example, consider the following search.

Replace the first and last functions when you use the stats and eventstats commands for ordering events based on time. The following search shows the function changes.

#### Wildcards in BY clauses

The stats command does not support wildcard characters in field values in BY clauses.

For example, you cannot specify | stats count BY source*.

#### Renaming fields

You cannot rename one field with multiple names. For example if you have field A, you cannot rename A as B, A as C.   The following example is not valid.

#### 1.  Return the average transfer rate for each host

#### 2. Search the access logs, and return the total number of hits from the top 100 values of "referer_domain"

Search the access logs, and return the total number of hits from the top 100 values of "referer_domain". The "top" command returns a count and percent value for each "referer_domain".

#### 3. Calculate the average time for each hour for similar fields using wildcard characters

Return the average, for each hour, of any unique field that ends with the string "lay". For example, delay, xdelay, relay, etc.

#### 4. Remove duplicates in the result set and return the total count for the unique results

Remove duplicates of results with the same "host" value and return the total count of the remaining results.

#### 5. In a multivalue BY field, remove duplicate values

For each unique value of mvfield, return the average value of field. Deduplicates the values in the mvfield.

#### 1. Compare the difference between using the stats and chart commands

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

This search uses the stats command to count the number of events for a combination of HTTP status code values and host:

The BY clause returns one row for each distinct value in the BY clause fields. In this search, because two fields are specified in the BY clause, every unique combination of status and host is listed on separate row.

The results appear on the Statistics tab and look something like this:

| status | host | count |
| --- | --- | --- |
| 200 | www1 | 11835 |
| 200 | www2 | 11186 |
| 200 | www3 | 11261 |
| 400 | www1 | 233 |
| 400 | www2 | 257 |
| 400 | www3 | 211 |
| 403 | www2 | 228 |
| 404 | www1 | 244 |
| 404 | www2 | 209 |

If you click the Visualization tab, the status field forms the X-axis and the host and count fields form the data series. The problem with this chart is that the host values (www1, www2, www3) are strings and cannot be measured in a chart.

Substitute the chart command for the stats command in the search.

With the chart command, the two fields specified after the BY clause change the appearance of the results on the Statistics tab. The BY clause also makes the results suitable for displaying the results in a chart visualization.

- The first field you specify is referred to as the <row-split> field. In the table, the values in this field become the labels for each row. In the chart, this field forms the X-axis.
- The second field you specify is referred to as the <column-split> field. In the table, the values in this field are used as headings for each column. In the chart, this field forms the data series.

The results appear on the Statistics tab and look something like this:

| status | www1 | www2 | www3 |
| --- | --- | --- | --- |
| 200 | 11835 | 11186 | 11261 |
| 400 | 233 | 257 | 211 |
| 403 | 0 | 288 | 0 |
| 404 | 244 | 209 | 237 |
| 406 | 258 | 228 | 224 |
| 408 | 267 | 243 | 246 |
| 500 | 225 | 262 | 246 |
| 503 | 324 | 299 | 329 |
| 505 | 242 | 0 | 238 |

If you click the Visualization tab, the status field forms the X-axis, the values in the host field form the data series, and the Y-axis shows the count.

#### 2. Use eval expressions to count the different types of requests against each Web server

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Run the following search to use the stats command to determine the number of different page requests, GET and POST, that occurred for each Web server.

This example uses eval expressions to specify the different field values for the stats command to count.

- The first clause uses the count() function to count the Web access events that contain the method field value GET. Then, using the AS keyword,  the field that represents these results is renamed GET.
- The second clause does the same for POST events.
- The counts of both types of events are then separated by the web server, using the BY clause with the host field.

The results appear on the Statistics tab and look something like this:

| host | GET | POST |
| --- | --- | --- |
| www1 | 8431 | 5197 |
| www2 | 8097 | 4815 |
| www3 | 8338 | 4654 |

Note: You can substitute the chart command for the stats command in this search. You can then click the Visualization tab to see a chart of the results.

#### 3. Calculate a wide range of statistics by a specific field

Count the number of earthquakes that occurred for each magnitude range

| This search uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance.  This example uses the All Earthquakes data from  the past 30 days. |

Run the following search to calculate the number of earthquakes that occurred in each magnitude range. This data set is comprised of events over a 30-day period.

- This search uses span=1 to define each of the ranges for the magnitude field, mag.
- The rename command is then used to rename the field to "Magnitude Range".

| Magnitude Range | Number of Earthquakes |
| --- | --- |
| -1-0 | 18 |
| 0-1 | 2088 |
| 1-2 | 3005 |
| 2-3 | 1026 |
| 3-4 | 194 |
| 4-5 | 452 |
| 5-4 | 109 |
| 6-7 | 11 |
| 7-8 | 3 |

Click the Visualization tab to see the result in a chart.

Search for earthquakes in and around California. Calculate the number of earthquakes that were recorded. Use  statistical functions to calculate the minimum, maximum, range (the difference between the min and max), and average magnitudes of the recent earthquakes. List the values by magnitude type.

The results appear on the Statistics tab and look something like this:

| magType | count | max(mag) | min(mag) | range(mag) | avg(mag) |
| --- | --- | --- | --- | --- | --- |
| H | 123 | 2.8 | 0.0 | 2.8 | 0.549593 |
| MbLg | 1 | 0 | 0 | 0 | 0.0000000 |
| Md | 1565 | 3.2 | 0.1 | 3.1 | 1.056486 |
| Me | 2 | 2.0 | 1.6 | .04 | 1.800000 |
| Ml | 1202 | 4.3 | -0.4 | 4.7 | 1.226622 |
| Mw | 6 | 4.9 | 3.0 | 1.9 | 3.650000 |
| ml | 10 | 1.56 | 0.19 | 1.37 | 0.934000 |

Search for earthquakes in and around California. Calculate the number of earthquakes that were recorded. Use  statistical functions to calculate the mean, standard deviation, and variance of the magnitudes for recent earthquakes. List the values by magnitude type.

The results appear on the Statistics tab and look something like this:

| magType | count | mean(mag) | std(mag) | var(mag) |
| --- | --- | --- | --- | --- |
| H | 123 | 0.549593 | 0.356985 | 0.127438 |
| MbLg | 1 | 0.000000 | 0.000000 | 0.000000 |
| Md | 1565 | 1.056486 | 0.580042 | 0.336449 |
| Me | 2 | 1.800000 | 0.346410 | 0.120000 |
| Ml | 1202 | 1.226622 | 0.629664 | 0.396476 |
| Mw | 6 | 3.650000 | 0.716240 | 0.513000 |
| ml | 10 | 0.934000 | 0.560401 | 0.314049 |

The mean values should be exactly the same as the values calculated using avg().

#### 4. In a table display items sold by ID, type, and name and calculate the revenue for each product

| This example uses the sample dataset from the Search Tutorial and a field lookup to add more information to the event data.
Download the data set from Add data tutorial and follow the instructions to load the tutorial data.Download the CSV file from Use field lookups tutorial and follow the instructions to set up the lookup definition to add price and productName to the events.
After you configure the field lookup, you can run this search using the time range, All time. |

Create a table that displays the items sold at the Buttercup Games online store by their ID, type, and name. Also, calculate the revenue for each product.

This example uses the values() function to display the corresponding categoryId and productName values for each productId. Then, it uses the sum() function to calculate a running total of the values of the price field.

Also, this example renames the various fields, for better display. For the stats functions, the renames are done inline with an "AS" clause. The rename command is used to change the name of the product_id field, since the syntax does not let you rename a split-by field.

Finally, the results are piped into an eval expression to reformat the Revenue field values so that they read as currency, with a dollar sign and commas.

This returns the following table of results:

#### 5. Determine how much email comes from each domain

| This example uses sample email data. You should be able to run this search on any email data by replacing the sourcetype=cisco:esa with the sourcetype value and the mailfrom field with email address field name in your data. For example, the email might be To, From, or Cc). |

Find out how much of the email in your organization comes from .com, .net, .org or other top level domains.

The eval command in this search contains two expressions, separated by a comma.

- The first part of this search uses the  command to break up the email address in the  field. The  is defined as the portion of the  field after the  symbol.
  - The split() function is used to break the mailfrom field into a multivalue field called accountname. The first value of accountname is everything before the "@" symbol, and the second value is everything after.
  - The mvindex() function is used to set from_domain to the second value in the multivalue field accountname.
- The results are then piped into the stats command. The count() function is used to count the results of the eval expression.
- Theeval uses the match() function to compare the from_domain to a regular expression that looks for the different suffixes in the domain. If the value of from_domain matches the regular expression, the count is updated for each suffix, .com, .net, and .org. Other domain suffixes are counted as other.

The results appear on the Statistics tab and look something like this:

| .com | .net | .org | other |
| --- | --- | --- | --- |
| 4246 | 9890 | 0 | 3543 |

#### 6. Search Web access logs for the total number of hits from the top 10 referring domains

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

This example searches the web access logs and return the total number of hits from the top 10 referring domains.

This search uses the top command to find the ten most common referer domains, which are values of the referer field. Some events might use referer_domain instead of  referer. The top command returns a count and percent value for each referer.

You can then use the  stats command to calculate a total for the top 10 referrer accesses.

The sum() function adds the values in the count to produce the total number of times the top 10 referrers accessed the web site.
 