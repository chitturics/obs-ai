---
 command: delta
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/delta
 title: delta
 download_date: 2026-02-03 09:04:47
---

 # delta

Computes the difference between nearby results using the value of a specific numeric field. For each event where <field> is a number, the delta command computes the difference, in search order, between the <field> value for the current event and the <field> value for the previous event. The delta command writes this difference into <newfield>.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The delta command works on the events in the order they are returned by search. By default, the events for historical searches are in reverse time order from new events to old events.

Values ascending over time show negative deltas.

For real-time search, the events are compared in the order they are received.

The delta can be applied after any sequence of commands, so there is no input order guaranteed. For example, if you sort your results by an independent field and then use the delta command, the produced values are the deltas in that specific order.

#### 1. Calculate the difference in activity

With the logs from a cable TV provider, sourcetype=tv, you can analyze broadcasting ratings, customer preferences, and so on. Which channels do subscribers watch the most, activity=view, and how long do the subscribers stay on those channels?

sourcetype=tv activity="View" | sort - _time | delta _time AS timeDeltaS | eval timeDeltaS=abs(timeDeltaS) | stats sum(timeDeltaS) by ChannelName

#### 2. Calculate the difference between that current value and the 3rd previous value

Compute the difference between current value of count and the 3rd previous value of count and store the result in the default field, delta(fieldname), which in this example is delta(count).

#### 3. Calculate the difference between that current value and the previous value and rename the result field

For each event where 'count' exists, compute the difference between count and its previous value and store the result in the field countdiff.

#### 1. Calculate the difference in the number of purchases between the top 10  buyers

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Find the top ten people who bought something yesterday, count how many purchases they made and the difference in the number of purchases between each buyer.

sourcetype=access_* status=200 action=purchase | top clientip | delta count p=1

- The purchase events, action=purchase, are piped into the top command to find the top ten users, based on clientip, who bought something.
- These results, which include a count for each clientip are then piped into the delta command to calculate the difference between the count value of one event and the count value of the event preceding it, using the p=1 argument.
- By default, this difference is saved in a new field called delta(count).
- The first event does not have a delta(count) value.

The results look something like this:

| clientip | count | percent | delta(count) |
| --- | --- | --- | --- |
| 87.194.216.51 | 134 | 2.565084 |  |
| 128.241.220.82 | 95 | 1.818530 | -39 |
| 211.166.11.101 | 91 | 1.741960 | -4 |
| 107.3.146.207 | 72 | 1.378254 | -19 |
| 194.215.205.19 | 60 | 1.148545 | -12 |
| 109.169.32.135 | 60 | 1.148545 | 0 |
| 188.138.40.166 | 56 | 1.071975 | -4 |
| 74.53.23.135 | 49 | 0.937979 | -7 |
| 187.231.45.62 | 48 | 0.918836 | -1 |
| 91.208.184.24 | 46 | 0.880551 | -2 |

#### 2. Calculate the difference in time between recent events

| This example uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and add it as an input. |

Calculate the difference in time between each of the recent earthquakes in Alaska. Run the search using the time range All time.

source=all_month.csv place=*alaska* | delta _time p=1  | rename delta(_time) AS timeDeltaS | eval timeDeltaS=abs(timeDeltaS) | eval "Time Between Quakes"=tostring(timeDeltaS,"duration") | table place, _time, "Time Between Quakes"

- This example searches for earthquakes in Alaska.

The delta command is used to calculate the difference in the timestamps, _time, between each earthquake and the one immediately before it. By default the difference is placed in a new field called delta(_time). The time is in seconds.

- The rename command is used to change the default field name to timeDeltaS.
- An eval command is used with the abs function to convert the time into the absolute value of the time. This conversion is necessary because the differences between one earthquake and the earthquake immediately before it result in negative values.
- Another eval command is used with the tostring function to convert the time, in seconds, into a string value. The duration argument is part of the tostring function that specifies to convert the value to a readable time format HH:MM:SS.

The results look something like this:

| place | _time | Time Between Quakes |
| --- | --- | --- |
| 32km N of Anchor Point, Alaska | 2018-04-04 19:51:19.147 |  |
| 6km NE of Healy, Alaska | 2018-04-04 16:26:14.741 | 03:25:04.406 |
| 34km NE of Valdez, Alaska | 2018-04-04 16:21:57.040 | 00:04:17.701 |
| 23km NE of Fairbanks, Alaska | 2018-04-04 16:10:05.595 | 00:11:51.445 |
| 53km SSE of Cantwell, Alaska | 2018-04-04 16:07:04.498 | 00:03:01.097 |
| 254km SE of Kodiak, Alaska | 2018-04-04 13:57:06.180 | 02:09:58.318 |
| 114km NNE of Arctic Village, Alaska | 2018-04-04 12:08:00.384 | 01:49:05.796 |
| 13km NNE of Larsen Bay, Alaska | 2018-04-04 11:49:21.816 | 00:18:38.568 |
| 109km W of Cantwell, Alaska | 2018-04-04 11:25:36.307 | 00:23:45.509 |
| 107km NW of Talkeetna, Alaska | 2018-04-04 10:26:21.610 | 00:59:14.697 |

#### 3. Calculate the difference in time between consecutive transactions

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Calculate the difference in time between consecutive transactions.

sourcetype=access_* | transaction JSESSIONID clientip startswith="view" endswith="purchase" | delta _time AS timeDelta p=1 | eval timeDelta=abs(timeDelta) | eval timeDelta=tostring(timeDelta,"duration")

- This example groups events into transactions if they have the same values of JSESSIONID and clientip.
- The beginning of a transaction is defined by an event that contains the string view. The end of a transaction is defined by an event that contains the string purchase. The keywords view and purchase correspond to the values of the action field. You might also notice other values for the action field,  such as addtocart and remove.
- The transactions are then piped into the delta command, which uses the _time field to calculate the time between one transaction and the transaction immediately preceding it. Specifically the difference between the timestamp for the last event in the transaction and the timestamp in the last event in the previous transaction.
- The search renames the time change as timeDelta.
- An eval command is used with the abs function to convert the time into the absolute value of the time. This conversion is necessary because the differences between one transaction and the previous transaction it result in negative values.
- Another eval command is used with the tostring function to convert the time, in seconds, into a string value. The duration argument is part of the tostring function that specifies to convert the value to a readable time format HH:MM:SS.
 