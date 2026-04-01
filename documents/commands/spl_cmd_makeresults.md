---
 command: makeresults
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/makeresults
 title: makeresults
 download_date: 2026-02-03 09:11:06
---

 # makeresults

Generates the specified number of search results in temporary memory.

If you do not specify any of the optional arguments, this command runs on the local machine and generates one result with only the _time field.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The makeresults command is a report-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

The search results created by the makeresults command are created in temporary memory and are not saved to disk or indexed.

You can use this command with the eval command to generate an empty result for the eval command to operate on. See the Examples section.

Note: Order-sensitive processors might fail if the internal _time field is absent.

#### Specifying server and server groups

If you use Splunk Cloud Platform, omit any server or server group argument.

If you are using Splunk Enterprise, by default results are generated only on the originating search head, which is equivalent to specifying splunk_server=local. If you provide a specific splunk_server or splunk_server_group, then the number of results you specify with the count argument are generated on the all servers or server groups that you specify.

If you specify a server, the results are generated for that server, regardless of the server group that the server is associated with.

If you specify a count of 5 and you target 3 servers, then you will generate 15 total results. If annotate=true, the names for each server appear in the splunk_server column. This column will show that each server produced 5 results.

#### Specifying servers for transparent mode federated searches

If you run Federated Search for Splunk in transparent mode, to run a makeresults search, you must use either the splunk_server or the splunk_server_group argument to identify the local or remote search head, search head cluster, indexer, or indexer cluster over which you want to run your makeresults search.

Note: If you do not identify the transparent mode server or servers that you want to run the search over, Splunk software blocks the makeresults search.

For example, if you want to run your search over a search head on your transparent mode federated provider, and that search head is named sh1.kualalumpur.blue, you must add splunk_server=sh1.kualalumpur.blue to your makeresults search.

For more information, see Run federated searches over remote Splunk platform deployments in Federated Search.

#### Generating results from inline CSV- or JSON-formatted data

Use the format and data arguments in conjunction to generate events from CSV- or JSON-formatted data.

Inline JSON data must be provided as a series of JSON objects, all within a single JSON array. The makeresults command generates a separate event for each JSON object. The keys of that object become fields, and the object values become field values. Each key must be bracketed in escape quotes. The entire JSON array must be placed within double quotation marks ( " ).

Here is an example of JSON formatted data:

Inline data in CSV format consists of a set of lines. The first line contains the schema, or headers, for the CSV table. This first line consists of a comma-separated list of strings, and each string corresponds to a field name. The schema ends when a newline character is reached. Each line following the schema line contains comma-separated field values, and each of these subsequent lines is translated by makeresults into an individual event. Use newlines to indicate the end of one event and the beginning of another.

Here is an example of CSV-formatted data:

Inline datasets cannot exceed a threshold of 29,999 characters.

If makeresults cannot parse the data for the specified format, it returns an error.

#### 1. Create a result as an input into the eval command

Sometimes you want to use the eval command as the first command in a search.  However, the eval command expects events as inputs. You can create a placeholder event at the beginning of a search by using the makeresults command. You can then use the eval command in your search.

The results look something like this:

| _time | newfield |
| --- | --- |
| 2020-01-09 14:35:58 | some value |

#### 2. Determine if the modified time of an event is greater than the relative time

For events that contain the field scheduled_time in UNIX time, determine if the scheduled time is greater than the relative time. The relative time is 1 minute before now. This search uses a subsearch that starts with the makeresults command.

#### 1. Create daily results for testing

You can use the makeresults command to create a series of results to test your search syntax.  For example, the following search creates a set of five results:

The results look something like this:

| _time |
| --- |
| 2020-01-09 14:35:58 |
| 2020-01-09 14:35:58 |
| 2020-01-09 14:35:58 |
| 2020-01-09 14:35:58 |
| 2020-01-09 14:35:58 |

Each result has the same timestamp which, by itself, is not very useful.  But with a few additions, you can create a set of unique dates. Start by adding the streamstats command to count your results:

The results look something like this:

| _time | count |
| --- | --- |
| 2020-01-09 14:35:58 | 1 |
| 2020-01-09 14:35:58 | 2 |
| 2020-01-09 14:35:58 | 3 |
| 2020-01-09 14:35:58 | 4 |
| 2020-01-09 14:35:58 | 5 |

You can now use that count to create different dates in the _time field, using the eval command.

The calculation multiplies the value in the count field by the number of seconds in a day. The result is subtracted from the original _time field to get new dates equivalent to 24 hours ago, 48 hours ago, and so forth.  The seconds in the date are different because _time is calculated the moment you run the search.

The results look something like this:

| _time | count |
| --- | --- |
| 2020-01-08 14:45:24 | 1 |
| 2020-01-07 14:45:24 | 2 |
| 2020-01-06 14:45:24 | 3 |
| 2020-01-05 14:45:24 | 4 |
| 2020-01-04 14:45:24 | 5 |

The dates start from the day before the original date, 2020-01-09, and go back five days.

Need more than five results?  Simply change the count value in the makeresults command.

#### 2. Create hourly results for testing

You can create a series of hours instead of a series of days for testing. Use 3600, the number of seconds in an hour, instead of 86400 in the eval command.

The results look something like this:

| _time | count |
| --- | --- |
| 2020-01-09 15:35:14 | 1 |
| 2020-01-09 14:35:14 | 2 |
| 2020-01-09 13:35:14 | 3 |
| 2020-01-09 12:35:14 | 4 |
| 2020-01-09 11:35:14 | 5 |

Notice that the hours in the timestamp are 1 hour apart.

#### 3. Add a field with string values

You can specify a list of values for a field. But to have the values appear in separate results, you need to make the list a multivalue field and then expand that multivalued list into separate results.  Use this search, substituting your strings for buttercup and her friends:

The results look something like this:

| _time | test |
| --- | --- |
| 2020-01-09 16:35:14 | buttercup |
| 2020-01-09 16:35:14 | rarity |
| 2020-01-09 16:35:14 | tenderhoof |
| 2020-01-09 16:35:14 | dash |
| 2020-01-09 16:35:14 | mcintosh |
| 2020-01-09 16:35:14 | fleetfoot |
| 2020-01-09 16:35:14 | mistmane |

#### 4. Create a set of events with multiple fields

Let's start by creating a set of four events. One of the events contains a null value in the age field.

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

In this example, the eventstats command generates the average age for each city. The generated averages are placed into a new field called avg(age).

The following search is the same as the previous search, with the eventstats command added at the end:

- For San Francisco, the average age is 28 = (25 + 31) / 2.
- For Seattle, there is only one event with a value. The average is 39 = 39 / 1. The eventstats command places that average in every event for Seattle, including events that did not contain a value for age.

The results of the search look like this:

| _time | age | avg(age) | city | count |
| --- | --- | --- | --- | --- |
| 2020-02-05 18:32:07 | 25 | 28 | San Francisco | 1 |
| 2020-02-05 18:32:07 | 39 | 39 | Seattle | 2 |
| 2020-02-05 18:32:07 | 31 | 28 | San Francisco | 3 |
| 2020-02-05 18:32:07 |  | 39 | Seattle | 4 |

#### 5. Add a field with a set of random numbers

If you need to test something with a set of numbers, you have two options:

- You can add a field with a set of numbers that you specify. This is similar to adding a field with a set of string values, which is shown in the previous example.
- You can add a field with a set of randomly generated numbers by using the random function, as shown below:

The results look something like this:

| _time | count | test |
| --- | --- | --- |
| 2020-01-08 14:45:24 | 1 | 5.371091109260495 |
| 2020-01-07 14:45:24 | 2 | 0.4563314783228324 |
| 2020-01-06 14:45:24 | 3 | 0.804991002129475 |
| 2020-01-05 14:45:24 | 4 | 1.4946919835236068 |
| 2020-01-04 14:45:24 | 5 | 24.193952675772845 |

Use the round function to round the numbers up.  For example, this search rounds the numbers up to four digits to the right of the decimal:

The results look something like this:

| _time | count | test |
| --- | --- | --- |
| 2020-01-08 14:45:24 | 1 | 5.3711 |
| 2020-01-07 14:45:24 | 2 | 0.4563 |
| 2020-01-06 14:45:24 | 3 | 0.8050 |
| 2020-01-05 14:45:24 | 4 | 1.4947 |
| 2020-01-04 14:45:24 | 5 | 24.1940 |

#### 6. Generate a table of results from JSON-formatted data

This makeresults search provides a JSON array of objects with the names and ages of a set of individuals.

makeresults transforms this JSON object array into a result table where the keys have been turned into fields and the values have been transformed into field values.

The results look something like this:

| _raw | _time | age | name |
| --- | --- | --- | --- |
| {"name":"Larson","age":32} | 2021-09-13 22:27:41 | 32 | Larson |
| {"name":"Nyeti","age":44} | 2021-09-13 22:27:41 | 44 | Nyeti |
| {"name":"Vero","age":22} | 2021-09-13 22:27:41 | 22 | Vero |

#### 7. Generate a table of results from CSV-formatted data

This makeresults search provides an inline collection of CSV-formatted data. It is a table containing the names and ages of a set of individuals.  You can add the fields command to reorder the fields so they do not appear in alphabetical order.

The results look something like this:

| name | age |
| --- | --- |
| Sujata | 61 |
| Linus | 29 |
| Karina | 33 |
 