---
 command: redistribute
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Redistribute
 title: redistribute
 download_date: 2026-02-03 09:14:41
---

 # redistribute

CAUTION: The redistribute command is an internal, unsupported, experimental command. See 
About internal commands.

The redistribute command implements parallel reduce search processing to shorten the search runtime of a set of supported SPL commands. Apply the redistribute command to high-cardinality dataset searches that aggregate large numbers of search results.

The redistribute command requires a distributed search environment where indexers have been configured to operate as intermediate reducers.

You can use the redistribute command only once in a search.

redistribute [num_of_reducers=<int>] [<by-clause>]

#### Required arguments

#### Optional arguments

In Splunk deployments that have distributed search, a two-phase map-reduce process is typically used to determine the final result set for the search. Search results are mapped at the indexer layer and then reduced at the search head.

The redistribute command inserts an intermediary reduce phase to the map-reduce process, making it a three-phase map-reduce-reduce process. This three-phase process is parallel reduce search processing.

In the intermediary reduce phase, a subset of the indexers become intermediate reducers. The intermediate reducers perform reduce operations for the search commands and then pass the results on to the search head, where the final result reduction and aggregation operations are performed. This parallelization of reduction work that otherwise would be done entirely by the search head can result in faster completion times for high-cardinality searches that aggregate large numbers of search results.

For information about managing parallel reduce processing at the indexer level, including configuring indexers to operate as intermediate reducers, see Overview of parallel reduce search processing, in the Distributed Search manual.

Note: If you use Splunk Cloud Platform, use redistribute only when your indexers are operating with a low to medium average load. You do not need to perform any configuration tasks to use the redistribute command.

#### Supported commands

The redistribute command supports only streaming commands and the following nonstreaming commands:

- stats
- tstats
- streamstats
- eventstats
- sichart
- sitimechart

The redistribute command also supports the transactioncommand, when the transaction command is operating on only one field. For example, the redistribute command cannot support the transactioncommand when the following conditions are true:

- The redistribute command has multiple fields in its <by-clause> argument.
- The transaction command has multiple fields in its <field-list> argument.
- You use the transactioncommand in a mode where no field is specified.

For best performance, place redistribute immediately before the first supported nonstreaming command that has high-cardinality input.

#### When search processing moves to the search head

The redistribute command moves the processing of a search string from the intermediate reducers to the search head in the following circumstances:

- It encounters a nonstreaming command that it does not support.
- It encounters a command that it supports but that does not include a split-by field.
- It encounters a command that it supports and that includes split-by fields, but the split-by fields are not a superset of the fields that are specified in the by-clause argument of the redistribute command.
- It detects that a command modifies values of the fields specified in the by-clause of the redistribute command.

#### Using the by-clause to determine how results are partitioned on the reducers

At the start of the intermediate reduce phase, the redistribute command takes the mapped search results and redistributes them into partitions on the intermediate reducers according to the fields specified by the by-clause argument. If you do not specify any by-clause fields, the search processor uses the field or fields that work best with the commands that follow the redistribute command in the search string.

#### Command type

The redistribute command is an orchestrating command, which means that it controls how a search runs. It does not focus on the events processed by the search. The redistribute command instructs the distributed search query planner to convert centralized streaming data into distributed streaming data by distributing it across the intermediate reducers.

For more information about command types, see Types of commands in the Search Manual.

#### Setting the default number of intermediate reducers

The default value for the num_of_reducers argument is controlled by three settings in the limits.conf file: maxReducersPerPhase, winningRate, and  reducers.

| Setting name | Definition | Default value |
| --- | --- | --- |
| maxReducersPerPhase | The maximum number of indexers that can be used as intermediate reducers in the intermediate reduce phase. | 4 |
| winningRate | The percentage of indexers that can be selected from the total pool of indexers and used as intermediate reducers in a parallel reduce search process. This setting applies only when the reducers setting is not configured. | 50 |
| reducers | A list of valid indexers that are to be used as dedicated intermediate reducers for parallel reduce search processing. When you run a search with the redistribute command, the valid indexers in the reducers list are the only indexers that are used for parallel reduce operations. If the number of valid indexers in the reducers list exceeds the maxReducersPerPhase value, the Splunk platform randomly selects a set of indexers from the reducers list that meets the maxReducersPerPhase limit. | " " (empty list) |

If you decide to add 7 of your indexers to the reducers list, the winningRate setting ceases to be applied, and the num_of_reducers argument defaults to 4 indexers. The Splunk platform randomly selects four indexers from the reducers list to act as intermediate reducers each time you run a valid redistribute search.

Note: If you provide a value for the num_of_reducers argument that exceeds the limit set by the maxReducersPerPhase setting, the Splunk platform sets the number of reducers to the maxReducersPerPhase value.

#### The redistribute command and search head data

Searches that use the redistribute command ignore all data on the search head. If you plan to use the redistribute command, the best practice is to forward all search head data to the indexer layer. See Best Practice: Forward search head data to the indexer layer in the Distributed Search manual.

#### Using the redistribute command in chart and timechart searches

If you want to add the redistribute command to a search that uses the chart or timechart commands to produce statistical results that can be used for chart visualizations, include either the sichart command or the sitimechart command in the search as well. The redistribute command uses these si- commands to perform the statistical calculations for the reporting commands on the intermediate reducers. When the redistribute command moves the results to the search head, the chart or timechart command transforms the results into a format that can be used for chart visualizations.

A best practice is to use the same syntax and values for both commands. For example, if you want to have | timechart count by referrer_domain in your redistribute search, insert | sitimechart count by referrer_domain into the search string:

#### If an order-sensitive command is present in the search

Certain commands that the redistribute command supports explicitly return results in a sorted order. As a result of the partitioning that takes place when the redistributecommand is run, the Splunk platform loses the sorting order. If the Splunk platform detects that an order-sensitive command, such as streamstats, is used in a redistribute search, it automatically inserts sort into the search as it processes it.

For example, the following search includes the streamstats command, which is order-sensitive:

The Splunk platform adds a sort segment before the streamstats segment when it processes the search. You can see the sort segment in the search string if you inspect the search job after you run it.

The stats and streamstats segments are processed on the intermediate reducers because they both split by the hostfield, the same field that the redistributecommand is distributing on. The work of the sort segment is split between the indexers during the map phase of the search and the search head during the final reduce phase of the search.

#### If you require sorted results from a redistribute search

If you require the results of a redistribute search to be sorted in that exact order, use sort to perform the sorting at the search head. There is an additional performance cost to event sorting after the redistribute command partitions events on the intermediate reducers.

The following search provides ordered results:

If you want to get that same event ordering while also adding redistribute to the search to speed it up, add sort to the search:

The stats segment of this search is processed on the intermediate reducers. The work of the sort segment is split between the indexers during the map phase of the search and the search head during the final reduce phase of the search.

#### Redistribute and virtual indexes

The redistribute command does not support searches of virtual indexes. The redistribute command also does not support unified searches if their time ranges are long enough that they run across virtual archive indexes.

#### 1. Speed up a search on a large high-cardinality dataset

In this example, the redistribute command is applied to a stats search that is running over an extremely large high-cardinality dataset. The redistribute command reduces the completion time for the search.

The intermediate reducers process the | stats count by ip portion of the search in parallel, lowering the completion time for the search. The search head aggregates the results.

#### 2. Speed up a timechart search without declaring a by-clause field to redistribute on

This example uses a search over an extremely large high-cardinality dataset. The search string includes the eventstats command, and it uses the sitimechart command to perform the statistical calculations for a timechart operation. The search uses the redistribute command to reduce the completion time for the search. A by-clause field is not specified, so the search processor selects one.

When this search runs,  the intermediate reducers process the eventstats and sitimechart segments of the search in parallel, reducing the overall completion time of the search. On the search head, the timechart command takes the reduced sitimechart calculations and transforms them into a format that can be used for for charts and visualizations.

Because a by-clause field is not identified in the search string, the intermediate reducers redistribute and partition events on the source field.

#### 3. Speed up a search that uses tstats to generate events

This example uses a search over an extremely large high-cardinality dataset. This search uses the tstats command in conjunction with the sitimechart and timechart commands. The redistribute command reduces the completion time for the search.

You have to place the tstats command at the start of the search string with a leading pipe character. When you use the redistribute command in conjunction with tstats, you must place the redistribute command after the tstats segment of the search.

In this example, the tstats command uses the prestats=t argument to work with the sitimechart and timechart commands.

The redistribute command causes the intermediate reducers to process the sitimechart segment of the search in parallel, reducing the overall completion time for the search. The reducers then push the results to the search head, where the timechart command processes them into a format that you can use for charts and visualizations.

#### 4. Speed up a search that includes a mix of supported and unsupported commands

This example uses a search over an extremely large high-cardinality dataset. The search uses the redistribute command to reduce the search completion time. The search includes commands that are both supported and unsupported by the redistribute command. It uses the sort command to sort of the results after the rest of the search has been processed. You need the  sort command for event sorting because the redistribute process undoes the sorting naturally provided by commands in the stats command family.

In this example, the intermediate reducers process the eventstats and where segments in parallel. Those portions of the search complete faster than they would when the redistribute command is not used.

The Splunk platform divides the work of processing the sort portion of the search between the indexer and the search head.

#### 5. Speed up a search where a supported command splits by fields that are not in the redistribute command by-clause argument

In this example, the redistribute command redistributes events across the intermediate reducers by the source field. The search includes two commands that are supported by the redistribute command but only one of them is processed on the intermediate reducers.

In this case, the eventstats segment of the search is processed in parallel by the intermediate reducers because it includes source as a split-by field. The where segment is also processed on the intermediate reducers.

The stats portion of the search, however, is processed on the search head because its split-by fields are not a superset of the set of fields that the events have been redistributed by. In other words, the stats split-by fields do not include source.
 