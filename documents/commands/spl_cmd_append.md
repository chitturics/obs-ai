---
 command: append
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/append
 title: append
 download_date: 2026-02-03 09:01:54
---

 # append

Appends the results of a subsearch to the current results.
The append command runs only over historical data and does not produce correct results if used in a real-time search.

By default, subsearches return a maximum of 10,000 results and have a maximum runtime of 60 seconds. If a subsearch runs for more than 60 seconds, its search results are automatically finalized.

For more information about when to use the append command, see the flowchart in the topic About event grouping and correlation in the Search Manual.

If you are familiar with SQL but new to SPL, see  Splunk SPL for SQL users.

append [<subsearch-options>...] <subsearch>

#### Required arguments

#### Optional arguments

#### Subsearch options

The append command is a transforming command. See Command types.

#### 1: Use the append command to add column totals.

| This search uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance.  This example uses the All Earthquakes data from the past 30 days. |

Count the number of earthquakes that occurred in and around California yesterday and then calculate the total number of earthquakes.

source=usgs place=*California* | stats count by magType | append [search index=usgs_* source=usgs place=*California* | stats count]

This example uses a subsearch to count all the earthquakes in the California regions (place="*California"), then uses the main search to count the number of earthquakes based on the magnitude type of the search.

You cannot use the stats command to simultaneously count the total number of events and the number of events for a specified field. The subsearch is used to count the total number of earthquakes that occurred. This count is added to the results of the previous search with the append command.

Because both searches share the count field, the results of the subsearch are listed as the last row in the count column.

The results appear on the Statistics tab and look something like this:

| magType | count |
| --- | --- |
| H | 123 |
| MbLg | 1 |
| Md | 1565 |
| Me | 2 |
| Ml | 1202 |
| Mw | 6 |
| ml | 10 |
|  | 2909 |

This search demonstrates how to use the append command in a way that is similar to using the addcoltotals command to add the column totals.

#### 2. Count the number of different customers who purchased items. Append the top purchaser for each type of product.

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Count the number of different customers who purchased something from the Buttercup Games online store yesterday, and break this count down by the type of product (accessories, t-shirts, and type of games) they purchased. Also, list the top purchaser for each type of product and how much that person bought of that product.

sourcetype=access_* action=purchase | stats dc(clientip) BY categoryId | append [search sourcetype=access_* action=purchase | top 1 clientip BY categoryId] | table categoryId, dc(clientip), clientip, count

This example first searches for purchase events (action=purchase). These results are piped into the stats command and the dc(), or distinct_count() function is used to count the number of different users who make purchases. The BY clause is used to break up this number based on the different category of products (categoryId).

This example contains a subsearch as an argument for the append command.

...[search sourcetype=access_* action=purchase | top 1 clientip BY categoryId]

The subsearch is used to search for purchase events and count the top purchaser (based on clientip) for each category of products. These results are added to the results of the previous search using the append command.

Here, the table command is used to display only the category of products (categoryId), the distinct count of users who bought each type of product (dc(clientip)), the actual user who bought the most of a product type (clientip), and the number of each product that user bought (count).

You can see that the append command just tacks on the results of the subsearch to the end of the previous search, even though the results share the same field values. It does not let you manipulate or reformat the output.

#### 3. Use the append command to determine the number of unique IP addresses that accessed the Web server.

Use the append command, along with the stats, count, and top commands to determine the number of unique IP addresses that accessed the Web server. Find the user who accessed the Web server the most for each type of page request.

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Count the number of different IP addresses that accessed the Web server and also find the user who accessed the Web server the most for each type of page request (method).

sourcetype=access_* | stats dc(clientip), count by method | append [search sourcetype=access_* | top 1 clientip by method]

The Web access events are piped into the stats command and the dc() or distinct_count() function is used to count the number of different users who accessed the site. The count() function is used to count the total number of times the site was accessed. These numbers are separated by the page request (method).

The subsearch is used to find the top user for each type of page request (method). The append command is used to add the result of the subsearch to the bottom of the table.

The results appear on the Statistics tab and look something like this:

| method | dc(clientip) | count | clientip | percent |
| --- | --- | --- | --- | --- |
| GET | 173 | 2666 |  |  |
| POST | 168 | 1727 |  |  |
| GET |  | 83 | 87.194.216.51 | 3.113278 |
| POST |  | 64 | 87.194.216.51 | 3.705848 |

```
method
```

```
count
```

#### 4. Specify the maximum time for the subsearch to run and the maximum number of result rows from the subsearch

Use the append command, to determine the number of unique IP addresses that accessed the Web server. Find the user who accessed the Web server the most for each type of page request.

| This example uses the sample dataset from the Search Tutorial but should work with any format of Apache web access log. Download the data set from this topic in the Search Tutorial and follow the instructions to upload it to your Splunk deployment. Use the time range Yesterday when you run this search. |

Count the number of different IP addresses that accessed the Web server and also find the user who accessed the Web server the most for each type of page request (method).  Limit the subsearch to 30 seconds and the maximum number of subsearch results to 1000.

sourcetype=access_* | stats dc(clientip), count by method | append maxtime=30 maxout=1000 [search sourcetype=access_* | top 1 clientip by method]

#### 5. Use the extendtimerange argument

Use the extendtimerange argument to ensure that the time range used for the search includes both the time range of the main search and the time range of the subsearch.

index=_internal earliest=11/20/2017:00:00:00 latest=11/30/2017:00:00:00 
|append extendtimerange=true 
   [search index=_audit earliest=11/1/2017:00:00:00 latest=11/25/2017:00:00:00] 
|timechart span=1d count

The time range used for the search is from 11/1/2017:00:00:00, the earliest time in the subsearch, to 11/30/2017:00:00:00, the latest time in the main search.

appendcols, appendpipe, join, set
 