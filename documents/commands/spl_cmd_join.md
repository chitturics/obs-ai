---
 command: join
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/join
 title: join
 download_date: 2026-02-03 09:09:55
---

 # join

You can use the join command to combine the results of a main search (left-side dataset) with the results of either another dataset or a subsearch (right-side dataset). You can also combine a search result set to itself using the selfjoin command.

The left-side dataset is the set of results from a search that is piped into the join command and then merged on the right side with the either a dataset or the results from a subsearch. The left-side dataset is sometimes referred to as the source data.

The following search example joins the source data from the search pipeline with a subsearch on the right side. Rows from each dataset are merged into a single row if the where predicate is satisfied.

A maximum of 50,000 rows in the right-side dataset can be joined with the left-side dataset over a maximum runtime of 60 seconds. These maximum defaults are set to limit the impact of the join command on performance and resource consumption.

If you are familiar with SQL but new to SPL, see  Splunk SPL for SQL users.

For flexibility and performance, consider using one of the following commands if you do not require join semantics.  These commands provide event grouping and correlations using time and geographic location, transactions, subsearches, field lookups, and joins.

| Command | Use |
| --- | --- |
| append | To append the results of a subsearch to the results of your current search. The events from both result sets are retained.
Use only with historical data. The append command does not produce correct results if used in a real-time search.If you use append to combine the events, use a stats command to group the events in a meaningful way.  You cannot use a transaction command after you use an append command. |
| appendcols | Appends the fields of the subsearch results with the input search result fields. The first subsearch result is merged with the first main result, the second subsearch result is merged with the second main result, and so on. |
| lookup | Use when one of the result sets or source files remains static or rarely changes. For example, a file from an external system such as a CSV file.
The lookup cannot be a subsearch. |
| search | In the most simple scenarios, you might need to search only for sources using the OR operator and then use a stats or transaction command to perform the grouping operation on the events. |
| stats | To group events by a field and perform a statistical function on the events. For example to determine the average duration of events by host name.
To use stats, the field must have a unique identifier.To view the raw event data, use the transaction command instead. |
| transaction | Use transaction in the following situations.
To group events by using the eval command with a conditional expression, such as if, case, or match.To group events by using a recycled field value, such as an ID or IP address.To group events by using a pattern, such as a start or end time for the event.To break up groups larger than a certain duration. For example, when a transaction does not explicitly end with a message and you want to specify a maximum span of time after the start of the transaction.To display the raw event data for the grouped events. |

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Descriptions for the join-options argument

The join command is a centralized streaming command when there is a defined set of fields to join to. Otherwise the command is a dataset processing command.
See Command types.

A subsearch can be initiated through a search command such as the join command. See Initiating subsearches with search commands in the Splunk Cloud Platform Search Manual.

#### Limitations on subsearches in joins

Use the join command when the results of the subsearch are relatively small, for example 50,000 rows or less. To minimize the impact of this command on performance and resource consumption, Splunk software imposes some default limitations on the subsearch.

Limitations on the subsearch for the join command are specified in the limits.conf file. The default limitations include a maximum of 50,000 rows in the subsearch to join against, and a maximum search time of 60 seconds for the subsearch. See Subsearches in the Search Manual.

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local.
- Under the [join] stanza, add the line subsearch_maxout = <value> or subsearch_maxtime = <value>.

#### One-to-many and many-to-many relationships

To return matches for one-to-many, many-to-one, or many-to-many relationships, include the max argument in your join syntax and set the value to 0.  By default max=1, which means that the subsearch returns only the first result from the subsearch.  Setting the value to a higher number or to 0, which is unlimited, returns multiple results from the subsearch.

#### 1. A basic join

Combine the results from a main search with the results from a subsearch search vendors. The result sets are joined on the product_id field, which is common to both sources.

#### 2. Returning all subsearch rows

By default, only the first row of the subsearch that matches a row of the main search is returned.  To return all of the matching subsearch rows, include the max=<int> argument and set the value to 0. This argument joins each matching subsearch row with the corresponding main search row.

#### 3. Join datasets on fields that have the same name

Combine the results from a search with the vendors dataset. The data is joined on the product_id field, which is common to both datasets.

#### 4. Join datasets on fields that have different names

Combine the results from a search with the vendors dataset. The data is joined on a product ID field, which have different field names in each dataset. The field in the left-side dataset is product_id. The field in the right-side dataset is pid.

#### 5. Use words instead of letters as aliases

You can use words for the aliases to help identify the datasets involved in the join. This example uses products and vendors for the aliases.

#### 6. Perform a case-insensitive join

Say you want to join a field with values that have prefixes that use both upper and lower case letters. But, the <field-list> argument for the join command is case sensitive. To work around this limitation, you can make the case consistent before and after you perform the join by using the lower() or upper() evaluation function. In this example, the value for the myfield field is converted to lower case, which makes the case consistent for the join command.

See Evaluation functions.

#### 1. Specifying dataset aliases with a saved search dataset

This example joins each matching right-side dataset row with the corresponding source data row. This example uses products, which is a savedsearch type of dataset, for the right-side dataset. The field names in the left-side dataset and the right-side dataset are different. This search returns all of the matching rows in the left and right datasets by including  max=0 in the search.

#### 2. Use aliasing with commands following the join

Commands following the join can take advantage of the aliasing provided through the join command. For example, you can use the aliasing in another command like stats as shown in the following example.

#### 3. Using a join to display resource usage information

The dashboards and alerts in the distributed management console shows you performance information about your Splunk deployment. The Resource Usage: Instance dashboard contains a table that shows the machine, number of cores, physical memory capacity, operating system, and CPU architecture.

To display the information in the table, use the following search. This search includes the join command. The search uses the information in the dmc_assets table to look up the instance name and machine name. The search then uses the serverName field to join the information with information from the  /services/server/info  REST endpoint. The /services/server/info  is the URI path to the Splunk REST API endpoint that provides hardware and operating system information for the machine. The  $splunk_server$ part of the search is a dashboard token variable.

selfjoin, append, set, appendcols
 