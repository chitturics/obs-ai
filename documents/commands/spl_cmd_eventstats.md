---
 command: eventstats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/eventstats
 title: eventstats
 download_date: 2026-02-03 09:06:22
---

 # eventstats

Generates summary statistics from fields in your events and saves those statistics in a new field.

Only those events that have fields pertinent to the aggregation are used in generating the summary statistics.  The generated summary statistics can be used for calculations in subsequent commands in your search. See Usage.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Stats function options

The eventstats command is a dataset processing command. See Command types.

The eventstats search processor uses a limits.conf file setting named max_mem_usage_mb to limit how much memory the eventstats command can use to keep track of information.  When the limit is reached, the eventstats command processor stops adding the requested fields to the search results.

Do not set max_mem_usage_mb=0 as this removes the bounds to the amount of memory the eventstats command processor can use. This can lead to search failures.

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local.
- Under the [default] stanza, look for the max_mem_usage_mb setting.
- Under Note, read the information about the eventstats command and how the max_mem_usage_mb and the maxresultrows settings are used to determine the maximum number of results to return.
- Change the value for the max_mem_usage_mb setting and if necessary the maxresultrows setting.

#### Differences between eventstats and stats

The eventstats command is similar to the stats command. You can use both commands to generate aggregations like average, sum, and maximum.

The differences between these commands are described in the following table:

| stats command | eventstats command |
| --- | --- |
| Events are transformed into a table of aggregated search results | Aggregations are placed into a new field that is added to each of the events in your output |
| You can only use the fields in your aggregated results in subsequent commands in the search | You can use the fields in your events in subsequent commands in your search, because the events have not been transformed |

#### How eventstats generates aggregations

The eventstats command looks for events that contain the field that you want to use to generate the aggregation. The command creates a new field in every event and places the aggregation in that field. The aggregation is added to every event, even events that were not used to generate the aggregation.

For example, you have 5 events and 3 of the events have the field you want to aggregate on. the eventstats command generates the aggregation based on the data in the 3 events. A new field is added to every event and the aggregation is added to that field in every event.

#### Statistical functions that are not applied to specific fields

With the exception of the count function, when you pair the eventstats command with functions that are not applied to specific fields or eval expressions that resolve into fields, the search head processes it as if it were applied to a wildcard for all fields. In other words, when you have | eventstats avg in a search, it returns results for | eventstats avg(*).

This "implicit wildcard" syntax is officially deprecated, however. Make the wildcard explicit. Write | eventstats <function>(*) when you want a function to apply to all possible fields.

#### Functions and memory usage

Some functions are inherently more expensive, from a memory standpoint, than other functions. For example, the distinct_count function requires far more memory than the count function. The values and list functions also can consume a lot of memory.

If you are using the distinct_count function without a split-by field or with a low-cardinality split-by by field, consider replacing the distinct_count function with the the estdc function (estimated distinct count).  The estdc function might result in significantly lower memory usage and run times.

#### Event order functions

Using the first and last functions when searching based on time does not produce accurate results.

- To locate the first value based on time order, use the earliest function, instead of the first function.
- To locate the last value based on time order, use the latest function, instead of the last function.

For example, consider the following search.

When you use the stats and eventstats commands for ordering events based on time, use the earliest and latest functions.

The following search is the same as the previous search except the first and last functions are replaced with the earliest and latest functions.

#### 1. Calculate the overall average duration

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Calculate the overall average duration of a set of transactions, and place the calculation in a new field called avgdur.

host=www1 
| transaction clientip host maxspan=30s maxpause=5s 
| eventstats avg(duration) AS avgdur

Because no BY clause is specified, a single aggregation is generated and added to every event in a new field called avgdur .

When you look at the list of Interesting Fields, you will see that avgdur has only one value.

#### 2. Calculate the average duration grouped by a specific field

This example is the same as the previous example except that an average is calculated for each distinct value of the date_minute field. The new field avgdur is added to each event with the average value based on its particular value of date_minute.

host=www1 
| transaction clientip host maxspan=30s maxpause=5s 
| eventstats avg(duration) As avgdur  BY date_minute

When you look at the list of Interesting Fields, you will see that avgdur has 79 values, based on the timestamp, duration, and date_minute values.

#### 3. Search for spikes in the volume of errors

This searches for spikes in error volume. You can use this search to trigger an alert if the count of errors is higher than average, for example.

eventtype="error" | eventstats avg(bytes) AS avg | where bytes>avg

The following example provides you with a better understanding of how the eventstats command works. This example is actually a progressive set of small examples, where one example builds on or extends the previous example.

It's much easier to see what the eventstats command does by showing you examples, using a set of simple events.

These examples use the makeresults command to create a set of events. The streamstats and eval commands are used to create additional fields in the events.

#### Creating a set of events

Let's start by creating a set of four events. One of the events contains a null value in the age field.

| makeresults count=4 
| streamstats count 
| eval age = case(count=1, 25, count=2, 39, count=3, 31, count=4, null())
| eval city = case(count=1 OR count=3, "San Francisco", count=2 OR count=4, "Seattle")

- The streamstats command is used to create the count field. The streamstats command  calculates a cumulative count for each event, at the time the event is processed.
- The eval command is used to create two new fields, age and city. The eval command uses the value in the count field.
- The case function takes pairs of arguments, such as count=1, 25. The first argument is a Boolean expression. When that expression is TRUE, the corresponding second argument is returned.

The results of the search look like this:

| _time | age | city | count |
| --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | San Francisco | 3 |
| 2020-02-05 18:32:07 |  | Seattle | 4 |

#### Using eventstats with a BY clause

The BY clause in the eventstats command is optional, but is used frequently with this command. The BY clause groups the generated statistics by the values in a field. You can use any of the statistical functions with the eventstats command to generate the statistics. See the Statistical and charting functions.

```
eventstats
```

```
avg(age)
```

The following search is the same as the previous search, with the eventstats command added at the end:

| makeresults count=4 
| streamstats count 
| eval age = case(count=1, 25, count=2, 39, count=3, 31, count=4, null())
| eval city = case(count=1 OR count=3, "San Francisco", count=2 OR count=4, "Seattle")
| eventstats avg(age) BY city

- For San Francisco, the average age is 28 = (25 + 31) / 2.
- For Seattle, there is only one event with a value. The average is 39 = 39 / 1. The eventstats command places that average in every event for Seattle, including events that did not contain a value for age.

The results of the search look like this:

| _time | age | avg(age) | city | count |
| --- | --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | 28 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 | 39 | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | 28 | San Francisco | 3 |
| 2020-02-05 18:32:07 |  | 39 | Seattle | 4 |

#### Renaming the new field

By default, the name of the new field that is generated is the name of the statistical calculation. In these examples, that name is avg(age). You can rename the new field using the AS keyword.

In the following search, the eventstats command has been adjusted to rename the new field to average age by city.

| makeresults count=4 
| streamstats count 
| eval age = case(count=1, 25, count=2, 39, count=3, 31, count=4, null())
| eval city = case(count=1 OR count=3, "San Francisco", count=2 OR count=4, "Seattle")
| eventstats avg(age) AS "average age by city" BY city

The results of the search look like this:

| _time | age | average age by city | city | count |
| --- | --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | 28 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 | 39 | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | 28 | San Francisco | 3 |
| 2020-02-05 18:32:07 |  | 39 | Seattle | 4 |

#### Events with text values

The previous examples show how an event is processed that does not contain a value in the age field. Let's see how   events are processed that contain an alphabetic character value in the field that you want to use to generate statistics .

The following search includes the word test as a value in the age field.

| makeresults count=4 
| streamstats count 
| eval age = case(count=1, 25, count=2, 39, count=3, 31, count=4, "test")
| eval city = case(count=1 OR count=3, "San Francisco", count=2 OR count=4, "Seattle")

| _time | age | city | count |
| --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | San Francisco | 3 |
| 2020-02-05 18:32:07 | test | Seattle | 4 |

```
eventstats
```

| makeresults count=4 
| streamstats count 
| eval age = case(count=1, 25, count=2, 39, count=3, 31, count=4, "test")
| eval city = case(count=1 OR count=3, "San Francisco", count=2 OR count=4, "Seattle")
| eventstats avg(age) BY city

| _time | age | avg(age) | city | count |
| --- | --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | 28 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 | 39 | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | 28 | San Francisco | 3 |
| 2020-02-05 18:32:07 | test | 39 | Seattle | 4 |

#### Using the allnum argument

But suppose you don't want statistics generated when there are alphabetic characters in the field or the field is empty?

The allnum argument controls how the eventstats command processes field values. The default setting for the allnum argument is FALSE. Which means that the field used to generate the statistics does not need to contain all numeric values.  Fields with empty values or alphabetic character values are ignored.  You've seen this in the earlier examples.

You can force the eventstats command to generate statistics only when the fields contain all numeric values. To accomplish this, you can set the allnum argument to TRUE.

| makeresults count=4 
| streamstats count 
| eval age = case(count=1, 25, count=2, 39, count=3, 31, count=4, "test")
| eval city = case(count=1 OR count=3, "San Francisco", count=2 OR count=4, "Seattle")
| eventstats allnum=true avg(age) BY city

| _time | age | avg(age) | city | count |
| --- | --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | 28 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 |  | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | 28 | San Francisco | 3 |
| 2020-02-05 18:32:07 | test |  | Seattle | 4 |

Because the age field contains values for Seattle that are not all numbers, the entire set of values for Seattle are ignored. No average is calculated.

The allnum=true argument applies to empty values as well as alphabetic character values.
 