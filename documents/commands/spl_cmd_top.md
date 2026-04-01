---
 command: top
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/top
 title: top
 download_date: 2026-02-03 09:19:40
---

 # top

Finds the most common values for the fields in the field list. Calculates a count and a percentage of the frequency the values occur in the events. If the <by-clause> is included, the results are grouped by the field you specify in the <by-clause>.

top [<N>] [<top-options>...] <field-list> [<by-clause>]

#### Required arguments

#### Optional arguments

#### Top options

The top command is a transforming command. See Command types.

#### Default fields

When you use the  top command, two fields are added to the results: count and percent.

| Field | Description |
| --- | --- |
| count | The number of events in your search results that contain the field values that are returned by the top command. See the countfield and showcount arguments. |
| percent | The percentage of events in your search results that contain the field values that are returned by the top command. See the percentfield and showperc arguments. |

#### Default maximum number of results

By default the top command returns a maximum of 50,000 results.
This maximum is controlled by the maxresultrows setting in the [top] stanza in the limits.conf  file. Increasing this limit can result in more memory usage.

Note: Only users with file system access, such as system administrators, can edit the configuration files. 
Never change or copy the configuration files in the default directory. The files in the default directory must remain intact and in their original location. Make the changes in the local directory.

See How to edit a configuration file.

If you have Splunk Cloud Platform, you need to file a Support ticket to change this limit.

#### Lexicographic order of results

In searches that use the limit option with multiple sets of field lists, only the last lexicographical value of the <field-list> is returned in the search results. For example, in the following search, Orlando is the only location field that is returned because it's the last value when sorted lexicographically.

The search results look something like this.

| user | location | count | percent |
| --- | --- | --- | --- |
| Alex | Orlando | 1 | 33.333333 |
| Kai | Orlando | 1 | 33.333333 |
| Morgan | Orlando | 1 | 33.333333 |

#### Example 1: Return the 20 most common values for a field

This search returns the 20 most common values of the "referer" field. The results show the number of events (count) that have that a count of  referer, and the percent that each referer is of the total number of events.

#### Example 2: Return top values for one field organized by another field

This search returns the top "action" values for each "referer_domain".

Because a limit is not specified, this returns all the combinations of values for "action" and "referer_domain" as well as the counts and percentages:

#### Example 3: Returns the top product purchased for each category

| This example uses the sample dataset from the Search Tutorial and a field lookup to add more information to the event data.
Download the data set from Add data tutorial and follow the instructions to load the tutorial data.Download the CSV file from Use field lookups tutorial and follow the instructions to set up the lookup definition to add price and productName to the events.
After you configure the field lookup, you can run this search using the time range, All time. |

This search returns the top product purchased for each category. Do not show the percent field. Rename the count field to "total".

rare, sitop, stats
 