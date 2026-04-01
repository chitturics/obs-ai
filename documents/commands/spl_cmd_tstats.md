---
 command: tstats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/tstats
 title: tstats
 download_date: 2026-02-03 09:20:17
---

 # tstats

Use the tstats command to perform statistical queries on indexed fields in tsidx files. The indexed fields can be from indexed data or accelerated data models.

Because it searches on index-time fields instead of raw events, the tstats command is faster than the stats command.

By default, the tstats command runs over accelerated and unaccelerated data models.

Note: Certain restricted search commands, including mpreview, mstats, tstats, typeahead, and walklex, might stop working if your organization uses field filters to protect sensitive data. See Plan for field filters in your organization in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### FROM clause arguments

The FROM clause is optional. See Selecting data for more information about this clause.

#### WHERE clause arguments

The optional WHERE clause is used as a filter. You can specify either a search or a field and a set of values with the IN operator.

WHERE clauses in tstat searches must contain field-value pairs that are indexed, as well as characters that are not major breakers or minor breakers. For example, consider the following search:

The results look something like this:

| sourcetype | count |
| --- | --- |
| splunkd | 2602154 |
| splunkd_access | 319019 |
| splunkd_conf | 19 |

This search returns valid results because sourcetype=splunkd* is an indexed field-value pair and wildcard characters are accepted in the search criteria. The asterisk at the end of the sourcetype=splunkd* clause is treated as a wildcard, and is not regarded as either a major or minor breaker.

#### BY clause arguments

The BY clause is optional. You cannot use wildcards in the BY clause with the tstats command. See Usage.  If you use the BY clause, you must specify a field-list. You can also specify a span.

The tstats command is a report-generating command, except when prestats=true. When prestats=true, the tstats command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search, except when  prestats=true.

By default, the tstats command runs over accelerated and unaccelerated data models.

Properly indexed fields should appear in the fields.conf file. See Create custom fields at index time in Getting Data In.

When you use a statistical function with the tstats command, you can't use an eval expression as part of the statistical function. See Complex aggregate functions.

#### Selecting data

Use the tstats command to perform statistical queries on indexed fields in tsidx files. You can select the data for the indexed fields in several ways.

#### Filtering data using the WHERE clause

You can use the optional WHERE clause to filter queries with the tstats command in much the same ways as you use it with the search command. For example, WHERE supports the same time arguments, such as earliest=-1y, with the tstats command and the search command.

WHERE clauses used in tstats searches can contain only indexed fields. Fields that are extracted at search time are not supported. If you don't know which of your fields are indexed, run a search on a specific index using the walklex  command.

#### Grouping data by _time

You can provide any number of BY fields. If you are grouping by _time, supply a timespan with span for grouping the time buckets, for example ...BY _time span=1h or ...BY _time span=3d.

#### Tstats and Federated Search for Splunk

tstats searches that include a FROM clause are blocked for transparent mode federated searches over federated providers with Splunk Cloud Platform versions lower than 9.0.2303 or Splunk Enterprise versions lower than 9.1.0. If you use multiple transparent mode federated providers, the tstats search is processed only on federated providers with qualifying versions.

For more information see About Federated Search for Splunk in Federated Search.

#### Tstats and tsidx bucket reduction

tstats searches over indexes that have undergone tsidx bucket reduction will return incorrect results.

For more information see Reduce tsidx disk usage in Managing indexers and clusters of indexers.

#### Sparkline charts

You can generate sparkline charts with the tstats command only if you specify the _time field in the BY clause and use the stats command to generate the actual sparkline. For example:

#### Multiple time ranges

The tstats command is unable to handle multiple time ranges. This is because the tstats command is a generating command and doesn't perform post-search filtering, which is required to return results for multiple time ranges.

The following example of a search using the tstats command on events with relative times of 5 seconds to 1 second in the past displays a warning that the results may be incorrect because the tstats command doesn't support multiple time ranges.

If you want to search events in multiple time ranges, use another command such as stats, or use multiple tstats commands with append as shown in the following example.

The results in this example look something like this.

| count |
| --- |
| 264 |

#### Wildcard characters

The tstats command does not support wildcard characters in field values in aggregate functions or BY clauses.

For example, you cannot specify | tstats avg(foo*) or | tstats count WHERE host=x BY source*.

Aggregate functions include avg(), count(), max(), min(), and sum(). For more information, see Aggregate functions.

Any results returned where the aggregate function or BY clause includes a wildcard character are only the most recent few minutes of data that has not been summarized. Include the summariesonly=t argument with your tstats command to return only summarized data.

#### Statistical functions must have named fields

With the exception of count, the tstats command supports only statistical functions that are applied to fields or eval expressions that resolve into fields. For example, you cannot specify | tstats sum or | tstats sum(). Instead the tstats syntax requires that at least one field argument be provided for the function: | tstats sum(<field>).

#### Nested eval expressions not supported

You cannot use eval expressions inside aggregate functions with the tstats command.

For example, | tstats count(eval(...)) is not supported.

While nested eval expressions are supported with the stats command, they are not supported with the tstats command.

#### Complex aggregate functions

The tstats command does not support complex aggregate functions such as ...count(eval('Authentication.action'=="failure")).

Consider the following query. This query will not return accurate results because complex aggregate functions are not supported by the tstats command.

Instead, separate out the aggregate functions from the eval functions, as shown in the following search.

The results from this search look something like this:

| uri | success |
| --- | --- |
| //services/cluster/config?output_mode=json | 0 |
| //services/cluster/config?output_mode=json | 2862 |
| /services/admin/kvstore-collectionstats?count=0 | 1 |
| /services/admin/transforms-lookup?count=0&getsize=true | 1 |

#### Limitations of CIDR matching with tstats

As with the search command, you can use the tstats command to filter events with CIDR match on fields that contain IPv4 and IPv6 addresses. However, unlike the search command, the tstats command may not correctly filter strings containing non-numeric wildcard octets. As a result, your searches may return unpredictable results.

If you are filtering fields with a CIDR match using the tstats command in a BY clause, you can work around this issue and correctly refilter your results by appending your search with a search command, regex command, or WHERE clause. Unfortunately, you can't use this workaround if the search doesn't include the filtered field in a BY clause.

#### Example of using CIDR match with tstats in a BY clause

Let's take a look at an example of how you could use CIDR match with the tstats command in a BY clause. Say you create a file called data.csv containing the following lines:

Then follow these steps:

- Upload the file and set the sourcetype to csv, which ensures that all fields in the file are indexed as required by the tstats command.
- Run the following search against the index you specified when you uploaded the file. This example uses the main index.

The results look like this:

| ip | count |
| --- | --- |
| 1.2.3.4 | 1 |
| 5.6.7.8 | 1 |
| this.is.a.hostname | 1 |
| this.is.another.hostname | 1 |

Even though only two addresses are legitimate IP addresses, all four rows of addresses are displayed in the results. Invalid IP addresses are displayed along with the valid IP addresses because the tstats command uses string matching to satisfy search requests and doesn't directly support IP address-based searches. The tstats command does its best to return the correct results for CIDR search clauses, but the tstats search may return more results than you want if the source data contains mixed IP and non-IP data such as host names.

To make sure your searches only return the results you want, make sure that your data set is clean and only contains data in the correct format. If that is not possible, use the search command or WHERE clause to do post-filtering of the search results. For example, the following search using the search command displays correct results because the piped search command further filters the results from the tstats command.

Alternatively, you can use the WHERE clause to filter your results, like this.

Both of these searches using the search command and the WHERE clause return only the valid IP addresses in the results, which look like this:

| ip | count |
| --- | --- |
| 1.2.3.4 | 1 |
| 5.6.7.8 | 1 |

#### The tstats command doesn't respect the srchTimeWin parameter

The tstats command doesn't respect the srchTimeWin parameter in the authorize.conf file and other role-based access controls that are intended to improve search performance. This is because the tstats command is already optimized for performance, which makes parameters like srchTimeWin irrelevant.

For example, say you previously set the srchTimeWin parameter on a role for one of your users named Alex, so they are just allowed to run searches back over 1 day. You limited the search time range to prevent searches from running over longer periods of time, which could potentially impact overall system performance and slow down searches for other users. Alex has been running a stats search, but didn't notice that they were getting results for just 1 day, even though they specified 30 days. If Alex then changes their search to a tstats search, or changes their search in such a way that Splunk software automatically optimizes it to a tstats search, the 1 day setting for the srchTimeWin parameter no longer applies. As a result, Alex gets many times more results than before, since their search is returning all 30 days of events, not just 1 day of results. This is expected behavior.

#### Use PREFIX() to aggregate or group by raw tokens in indexed data

The PREFIX() directive allows you to search on a raw segment in your indexed data as if it were an extracted field. This causes the search to run over the tsidx file in your indexers rather than the log line. This is a practice that can significantly reduce the CPU load on your indexers.

The PREFIX() directive is similar to the CASE() and TERM() directives in that it matches strings in your raw data. You can use PREFIX() to locate a recurring segment in your raw event data that is actually a key-value pair separated by a delimiter that is also a minor breaker, like = or :. You give PREFIX() the text that precedes the value, which is the "prefix", and then the search returns the values that follow the prefix. This enables you to group by those values and aggregate them with tstats functions. The values can be strings or purely numeric.

For example, say you have indexed segments in your event data that look like kbps=10 or kbps=333. You can isolate the numerical values in these segments and perform aggregations or group-by operations on them by using the PREFIX() directive to identify kbps= as a common prefix string. Run a tstats search with PREFIX(kbps=) against your event data and it will return 10 and 333. These values are perfect for tstats aggregation functions that require purely numeric input.

Notice that in this example you need to include the = delimiter. If you run PREFIX(kbps), the search returns =10 and =333. Efforts to aggregate on such results may return unexpected results, especially if you are running them through aggregation functions that require purely numeric values.

Note: The text you provide for the PREFIX() directive must be in lower case. For example, the tstats search processor will fail to process PREFIX(connectionType=). Use PREFIX(connectiontype=) instead. It will still match connectionType= strings in your events.

The Splunk software separates events into raw segments when it indexes data, using rules specified in segmenters.conf. You can run the following search to identify raw segments in your indexed events:

Note: You cannot apply the PREFIX() directive to segment prefixes and values that contain major breakers such as spaces, square or curly brackets, parentheses, semicolons, or exclamation points.

For more information about the CASE() and TERM() directives, see Use CASE() and TERM() to match phrases in the Search Manual.

For more information about the segmentation of indexed events, see About event segmentation in Getting Data In

For more information about minor and major breakers in segments, see Event segmentation and searching in the Search Manual.

#### Memory and tstats search performance

A pair of limits.conf settings strike a balance between the performance of tstats searches and the amount of memory they use during the search process, in RAM and on disk. If your tstats searches are consistently slow to complete you can adjust these settings to improve their performance, but at the cost of increased search-time memory usage, which can lead to search failures.

If you have Splunk Cloud Platform, you need to file a Support ticket to change these settings.

For more information, see Memory and stats search performance in the Search Manual.

#### Functions and memory usage

Some functions are inherently more expensive, from a memory standpoint, than other functions. For example, the distinct_count function requires far more memory than the count function. The values and list functions also can consume a lot of memory.

If you are using the distinct_count function without a split-by field or with a low-cardinality split-by by field, consider replacing the distinct_count function with the estdc function (estimated distinct count). The estdc function might result in significantly lower memory usage and run times.

#### 1. Get a count of all events in an index

This search tells you how many events there are in the  _internal index.

#### 2. Use a filter to get the average

This search returns the average of the field size in myindex, specifically where test is value2 and the value of result is greater than 5. Both test and result are indexed fields.

#### 3.  Return the count by splitting by source

This search gives the count by source for events with host=x.

#### 4.  Produce a timechart

This search produces a timechart of all the data in your default indexes with a day granularity. To avoid unpredictable results, the value of the tstats span argument should be smaller than or equal to the value of the timechart span argument.

#### 5.  Use summariesonly to get a time range of summarized data

This search uses the summariesonly argument to get the time range of the summary for an accelerated data model named mydm.

#### 6. Find out how much data has been summarized

This search uses summariesonly in conjunction with the timechart command to reveal the data that has been summarized in 1 hour blocks of time for an accelerated data model called mydm.

The span argument indicates how the events are grouped into buckets or blocks of time, but it doesn't indicate how long the search should run. To run your search over a specific length of time, use the time range picker in the Search app to set the time window for your search. Alternatively, you can include a WHERE clause in your search like this, which searches events in 1 hour blocks across a 3 hour time window:

#### 7. Get a list of values for source returned by the internal log data model

This search uses the values statistical function to provide a list of all distinct values for the source that is returned by the internal log data model. The list is returned as a multivalue entry.

The results look something like this:

| values(source) |
| --- |
| /Applications/Splunk/var/log/splunk/license_usage.log
/Applications/Splunk/var/log/splunk/metrics.log
/Applications/Splunk/var/log/splunk/metrics.log.1
/Applications/Splunk/var/log/splunk/scheduler.log
/Applications/Splunk/var/log/splunk/splunkd.log
/Applications/Splunk/var/log/splunk/splunkd_access.log |

Note: If you don't have the internal_server data model defined, check under Settings->Data models for a list of the data models you have access to.

#### 8. Get a list of values for source returned by the Alerts dataset in the internal log data model

This search uses the values statistical function to provide a list of all distinct values for source returned by the Alerts dataset within the internal log data model.

#### 9. Get the count and average

This search gets the count and average of a raw, unindexed term using the PREFIX kbps=, then splits this by an indexed source and another unindexed term using the PREFIX group=.
 