---
 command: streamstats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/streamstats
 title: streamstats
 download_date: 2026-02-03 09:18:22
---

 # streamstats

Adds cumulative summary statistics to all search results in a streaming manner. The streamstats command calculates statistics for each event at the time the event is seen.  For example, you can calculate the running total for a particular field. The total is calculated by using the values in the specified field for every event that has been processed, up to the current event.

As the streamstats command processes each event, it adds a field to that event or result that represents the accumulation of all of the events before it in the time window. The value of that field changes per event or result as the composition of events in the window or result set changes. In other words, the streamstats command produces a running total that is applied to each event, or the result of another transforming search, as they stream in. The streamstats command operates on whatever search output it receives and is the accumulation of the average, sum, count or so on, of one the following two elements:

- All of the events in the search window that have been collected up to that point, if a window is applied. If you don't set the time_window or the window arguments, the default of 10,000 events set by the max_stream_window in the limits.conf file applies to your streamstats searches. See Optional arguments.

- The results returned by a transforming command, such as the stats, chart, or timechart command, as each result is received and the running total of the events preceding that result is applied to it.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Stats function options

The streamstats command is a centralized streaming command. See Command types.

The streamstats command is similar to the eventstats command except that it uses events before the current event to compute the aggregate statistics that are applied to each event. If you want to include the current event in the statistical calculations, use current=true, which is the default.

The streamstats command is also similar to the stats command in that streamstats calculates summary statistics on search results. Unlike stats, which works on the group of results as a whole, streamstats calculates statistics for each event at the time the event is seen.

#### Statistical functions that are not applied to specific fields

With the exception of the count function, when you pair the streamstats command with functions that are not applied to specific fields or eval expressions that resolve into fields, the search head processes it as if it were applied to a wildcard for all fields. In other words, when you have | streamstats avg in a search, it returns results for | stats avg(*).

This "implicit wildcard" syntax is officially deprecated, however. Make the wildcard explicit. Write | streamstats <function>(*) when you want a function to apply to all possible fields.

#### Escaping string values

If your <eval-expression> contains a value instead of a field name, you must escape the quotation marks around the value.

The following example is a simple way to see this. Start by using the makeresults command to create 3 events. Use the streamstats command to produce a cumulative count of the events. Then use the eval command to create a simple test.  If the value of the count field is equal to 2, display yes in the test field. Otherwise display no in the test field.

The results appear something like this:

| _time | count | test |
| --- | --- | --- |
| 2017-01-11 11:32:43 | 1 | no |
| 2017-01-11 11:32:43 | 2 | yes |
| 2017-01-11 11:32:43 | 3 | no |

Use the streamstats command to reset the count when the match is true. You must escape the quotation marks around the word yes. The following example shows the complete search.

Here is another example. 
You want to look for the value session is closed in the description field. Because the value is a string, you must enclose it in quotation marks.  You then need to escape those quotation marks.

#### The reset_on_change argument

You have a dataset with the field "shift" that contains either the value DAY or the value NIGHT. You run this search:

If  the dataset is:

Running the command with reset_on_change=true produces the following streamstats results:

#### Memory and maximum results

The streamstats search processor uses two limits.conf settings to determine the maximum number of results that it can store in memory for the purpose of computing statistics.

The maxresultrows setting specifies a top limit for the window argument. This sets the number of result rows that the streamstats command processor can store in memory. The max_mem_usage_mb setting limits how much memory the streamstats command uses to keep track of information.

When the max_mem_usage_mb limit is reached, the streamstats command processor stops adding the requested fields to the search results.

Do not set max_mem_usage_mb=0 as this removes the bounds to the amount of memory the streamstats command processor can use. This can lead to search failures.

Prerequisites

- Only users with file system access, such as system administrators, can increase the maxresultrows and max_mem_usage_mb settings using configuration files.
- Review the steps in How to edit a configuration file in the Splunk Enterprise Admin Manual.
- You can have configuration files with the same name in your default, local, and app directories. Read Where you can place (or find) your modified configuration files in the Splunk Enterprise Admin Manual.

CAUTION: Never change or copy the configuration files in the default directory. The files in the default directory must remain intact and in their original location. Make changes to the files in the local directory.

If you have Splunk Cloud Platform and want to change these limits, file a Support ticket.

#### 1. Compute the average of a field over the last 5 events

For each event, compute the average of the foo field over the last 5 events, including the current event.

This is similar to using the trendline command to compute a simple moving average (SMA), such as  trendline sma5(foo).

#### 2. Compute the average of a field, with a by clause, over the last 5 events

For each event, compute the average value of foo for each value of bar including only 5 events, specified by the window size, with that value of bar.

#### 3. For each event, add a count of the number of events processed

This example adds to each event a count field that represents the number of events seen so far, including that event. For example, it adds 1 for the first event, 2 for the second event, and so on.

If you did not want to include the current event, you would specify:

#### 4. Apply a time-based window to streamstats

Assume that the max_stream_window argument in the limits.conf file is the default value of 10000 events.

The following search counts the events, using a time window of five minutes.

This search adds a count field to each event.

- If the events are in descending time order (most recent to oldest), the value in the count field represents the number of events in the next 5 minutes.
- If the events are in ascending time order (oldest to most recent), the count field represents the number of events in the previous 5 minutes.

If there are more events in the time-based window than the value for the max_stream_window argument, the max_stream_window argument takes precedence.  The count will never be greater than 10000, even if there are actually more than 10,000 events in any 5 minute period.

#### 1. Create events for testing

You can use the streamstats command with the makeresults command to create a series events. This technique is often used for testing search syntax. The eval command is used to create events with different hours. You use 3600, the number of seconds in an hour, in the eval command.

The makeresults command is used to create the count field. The streamstats command calculates a cumulative count for each event, at the time the event is processed.

The results look something like this:

| _time | count |
| --- | --- |
| 2020-01-09 15:35:14 | 1 |
| 2020-01-09 14:35:14 | 2 |
| 2020-01-09 13:35:14 | 3 |
| 2020-01-09 12:35:14 | 4 |
| 2020-01-09 11:35:14 | 5 |

Notice that the hours in the timestamp are 1 hour apart.

You can create additional fields by using the eval command.

- The eval command is used to create two new fields, age and city. The eval command uses the value in the count field.
- The case function takes pairs of arguments, such as count=1, 25. The first argument is a Boolean expression. When that expression is TRUE, the corresponding second argument is returned.

The results of the search look like this:

| _time | age | city | count |
| --- | --- | --- | --- |
| 2020-01-09 15:35:14 | 25 | San Francisco | 1 |
| 2020-01-09 14:35:14 | 39 | Seattle | 2 |
| 2020-01-09 13:35:14 | 31 | San Francisco | 3 |
| 2020-01-09 12:35:14 | 27 | Seattle | 4 |
| 2020-01-09 11:35:14 |  | Los Angeles | 5 |

#### 2. Calculate a snapshot of summary statistics

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

You want to determine the number of the bytes used over a set period of time. The following search uses the first 5 events. Because search results typically display the most recent event first, the sort command is used to sort the 5 events in ascending order to see the oldest event first and the most recent event last. Ascending order enables the streamstats command to calculate statistics over time.

```
streamstats
```

```
clientip
```

```
ASimpleSumOfBytes
```

The streamstats command aggregates the statistics to the original data, which means that all of the original data is accessible for further calculations.

```
table
```

```
_time
```

```
clientip
```

```
bytes
```

```
ASimpleSumOfBytes
```

Each event shows the timestamp for the event, the clientip, and the number of  bytes used.  The ASimpleSumOfBytes field shows a cumulative summary of the bytes for each clientip.

#### 3. Calculate the running total of distinct users over time

Each day you track unique users, and you would like to track the cumulative count of distinct users. This example calculates the running total of distinct users over time.

The bin command breaks the time into days. The stats command calculates the distinct users (clientip) and user count per day. The streamstats command finds the running distinct count of users.

This search returns a table that includes: day, ips, dc(clientip), and Cumulative total.

#### 4. Calculate hourly cumulative totals

This example uses streamstats to produce hourly cumulative totals.

This search returns 3 columns: _time, SumOfBytes, and accu_total_SumOfBytes.

The timechart command buckets the events into spans of 1 hour and counts the total values for each category. The timechart command also fills NULL values, so that there are no missing values. Then, the streamstats command is used to calculate the accumulated total.

```
streamstats
```

#### 5. Calculate when a DHCP IP lease address changed for a specific MAC address

This example uses streamstats to figure out when a DHCP IP lease address changed for a MAC address, 54:00:00:00:00:00.

You can also clean up the presentation to display a table of the DHCP IP address changes and the times the occurred.

For more details, refer to the Splunk Blogs post for this example.

#### 6. Compare a number with itself over a few months

Say a community needs to find out how their vaccination booster campaign is going. They want to check the gap after their citizens get the second booster shot, which should keep up with their target of about 6 months between the second and third doses. The following search is across the daily number of people by number of doses.

The search results return a graph that looks something like this, with 3 lines for the second booster showing the gap at 5 months, 6 months, and 7 months, which shows that the community is almost keeping up with a 6-month booster gap:
 