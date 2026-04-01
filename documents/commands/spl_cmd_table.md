---
 command: table
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/table
 title: table
 download_date: 2026-02-03 09:18:42
---

 # table

The table command returns a table that is formed by only the fields that you specify in the arguments. Columns are displayed in the same order that fields are specified. Column headers are the field names. Rows are the field values. Each row represents an event.

The table command is similar to the fields command in that it lets you specify the fields you want to keep in your results. Use table command when you want to retain data in tabular format.

With the exception of a scatter plot to show trends in the relationships between discrete values of your data, you should not use the table command for charts.  See Usage.

To optimize searches, avoid putting the table command in the middle of your searches and instead, put it at the end of your searches.

table <wc-field-list>

#### Arguments

The table command is a transforming command. See Command types.

#### Visualizations

To generate visualizations, the search results must contain numeric, datetime, or aggregated data such as count, sum, or average.

#### Command type

The table command is a non-streaming command.  If you are looking for a streaming command similar to the table command, use the fields command.

#### Field renaming

The table command doesn't let you rename fields, only specify the fields that you want to show in your tabulated results. If you're going to rename a field, do it before piping the results to table.

#### Truncated results

The table command truncates the number of results returned based on settings in the limits.conf file. In the [search] stanza,  if the value for the truncate_report parameter is 1, the number of results returned is truncated.

The number of results is controlled by the max_count parameter in the [search] stanza. If truncate_report is set to 0, the max_count parameter is not applied.

#### Example 1

| This example uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), and so forth, for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance if you want follow along with this example. |

Search for recent earthquakes in and around California and display only the time of the quake (time), where it occurred (place), and the quake's magnitude (mag) and depth (depth).

This search reformats your events into a table and displays only the fields that you specified as arguments. The results look something like this:

| time | place | mag | depth |
| --- | --- | --- | --- |
| 2023-03-06T06:45:17.427Z | 0 km S of Carnelian Bay, California | 0.2 | 8 |
| 2023-03-06T12:49:26.451Z | 35 km NE of Independence, California | 0.7 | 0 |
| 2023-03-07T09:22:15.281Z | 16 km ENE of Doyle, California | 0.4 | 11 |
| 2023-03-07T09:37:03.042Z | Northern California | 0.4 | 0 |
| 2023-03-07T16:41:29.557Z | 27 km ENE of Herlong, California | 1 | 0 |
| 2023-03-07T20:57:11.181Z | 259 km W of Ferndale, California | 3.3 | 16.554 |

#### Example 2

| This example uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), and so forth, for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance if you want follow along with this example. |

Show the date, time, coordinates, and magnitude of each recent earthquake in Northern California.

This example begins with a search for all recent earthquakes in Northern California (place="Northern California").

Then the events are piped into the rename command to change the names of the coordinate fields, from latitude and longitude to  lat and lon. The locationSource field is also renamed to locSource. (The table command doesn't let you rename or reformat fields, only specify the fields that you want to show in your tabulated results.)

Finally, the results are piped into the table command, which specifies both coordinate fields with lat and lon, the date and time with time, and locSource using the asterisk wildcard. The results look something like this:

| time | place | lat | lon | locSource |
| --- | --- | --- | --- | --- |
| 2023-03-03T13:32:16.019Z | Northern California | 39.3547 | -120.0101 | nn |
| 2023-03-07T09:37:03.042Z | Northern California | 39.6117 | -120.7116 | nn |
| 2023-03-09T03:56:40.162Z | Northern California | 39.3561 | -120.0133 | nn |
| 2023-03-01T09:37:57.283Z | Northern California | 39.5293 | -120.3513 | nn |
| 2023-02-21T05:18:39.039Z | Northern California | 39.6726 | -120.642 | nn |

#### Example 3

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Search for IP addresses and classify the network they belong to.

This example searches for Web access data and uses the dedup command to remove duplicate values of the IP addresses (clientip) that access the server. These results are piped into the eval command, which uses the cidrmatch() function to compare the IP addresses to a subnet range (192.0.0.0/16). This search also uses the if() function, which specifies that if the value of clientip falls in the subnet range, then the network field is given the value local. Otherwise, the network field is other.

The results are then piped into the table command to show only the distinct IP addresses (clientip) and the network classification (network). The results look something like this:

| clientip | network |
| --- | --- |
| 192.0.1.51 | other |
| 192.168.11.33 | other |
| 192.168.11.44 | other |
| 192.168.11.35 | other |
| 192.1.2.40 | other |
| 192.1.2.35 | other |
| 192.0.1.39 | local |

#### Example 4

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Create a table with the fields host, action, and all fields that start with date_m.

The results look something like this:

| host | action | date_mday | date_minute | date_month |
| --- | --- | --- | --- | --- |
| www1 |  | 20 | 51 | july |
| www1 |  | 20 | 48 | july |
| www1 |  | 20 | 48 | july |
| www1 | addtocart | 20 | 48 | july |
| www1 |  | 20 | 48 | july |
 