---
 command: union
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/union
 title: union
 download_date: 2026-02-03 09:20:40
---

 # union

Merges the results from two or more datasets into one dataset. One of the datasets can be a result set that is then piped into the union command and merged with a second dataset.

The union command appends or merges event from the specified datasets, depending on whether the dataset is streaming or non-streaming and where the command is run.  The union command runs on indexers in parallel where possible, and automatically interleaves results on the _time when processing events. See Usage.

If you are familiar with SQL but new to SPL, see  Splunk SPL for SQL users.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The union command is a dataset processing command. See Command types.

How the union command processes datasets depends on whether the dataset is a streaming or non-streaming dataset. The type of dataset is determined by the commands that are used to create the dataset.  
See Types of commands.

Note: There are two types of streaming commands, distributable streaming and centralized streaming. For this discussion about the union command, streaming datasets refers to distributable streaming.

A subsearch can be initiated through a search command such as the union command. See Initiating subsearches with search commands in the Splunk Cloud Platform Search Manual.

#### Where the command is run

Whether the datasets are streaming or non-streaming determines if the union command is run on the indexers or the search head.  The following table specifies where the command is run.

| Dataset type | Dataset 1 is streaming | Dataset 1 is non-streaming |
| --- | --- | --- |
| Dataset 2 is streaming | Indexers | Search head |
| Dataset 2 is non-streaming | Search head | Search head |

#### How the command is processed

The type of dataset also determines how the union command is processed.

| Dataset type | Impact on processing |
| --- | --- |
| Centralized streaming or non-streaming | Processed as an append command. |
| Distributable streaming | Processed as a multisearch command.

Placing <streaming_dataset1> after the union command is more efficient. |

#### Optimized syntax for streaming datasets

With streaming datasets, instead of this syntax:

Your search is more efficient with this syntax:

#### Why unioned results might be truncated

Consider the following search, which uses the union command to merge the events from three indexes. Each index contains 60,000 events, for a total of 180,000 events.

| index | count |
| --- | --- |
| union_1 | 60000 |
| union_2 | 60000 |
| union_3 | 60000 |

In this example, all of the subsearches are distributable streaming, so they are unioned by using same processing as the multisearch command. All 60,000 results for each index are unioned for a total of 180,000 merged events.

However, if you specify a centralized streaming command, such as  the head command, in one of the subsearches the results change.

This search produces the following union results for a total of 160,000 merged events.

| index | count |
| --- | --- |
| union_1 | 60000 |
| union_2 | 50000 |
| union_3 | 50000 |

Because the head command is a centralized streaming command rather than distributable streaming command, any subsearches that follow the head command are processed using the append command. In other words, when a command forces the processing to the search head, all subsequent commands must also be processed on the search head.

Internally, the search is converted to this:

When the union command is used with commands that are non-streaming commands, the default for the maxout argument is enforced. The default for the maxout argument is 50,000 events.  In this example, the default for the maxout argument is enforced starting with the subsearch that used the non-streaming command. The default is enforced for any subsequent subsearches.

If the non-streaming command is on the last subsearch, the first two subsearches are processed as streaming. These subsearches are unioned using the multisearch command processing. The final subsearch includes a non-streaming command, the head command. That subsearch gets unioned using the append command processing.

Internally this search is converted to this:

In this example, the default for the maxout argument applies only to the last subsearch. That subsearch returns only 50,000 events instead of the entire set of 60,000 events. The total number events merged is 170,000. 60,000 events for the first and second subsearches and 50,000 events from the last subsearch.

#### Interleaving results

When two datasets are retrieved from disk in descending time order, which is the default sort order, the union command interleaves the results. The interleave is based on the _time field.  For example, you have the following datasets:

| _time | host | bytes |
| --- | --- | --- |
| 4 | mailsrv1 | 2412 |
| 1 | dns15 | 231 |

| _time | host | bytes |
| --- | --- | --- |
| 3 | router1 | 23 |
| 2 | dns12 | 22o |

```
_time
```

```
| union dataset_A, dataset_B
```

| _time | host | bytes |
| --- | --- | --- |
| 4 | mailsrv1 | 2412 |
| 3 | router1 | 23 |
| 2 | dns12 | 22o |
| 1 | dns15 | 231 |

#### 1. Union events from two subsearches

The following example merges events from index a and index b. New fields type and mytype are added in each subsearch using the eval command.

#### 2. Union the results of a subsearch to the results of the main search

The following example appends the current results of the main search with the tabular results of errors from the subsearch.

#### 3. Union events from a data model and events from an index

The following example unions a built-in data model that is an internal server log for REST API calls and the events from index a.

#### 4. Specify the subsearch options

The following example sets a maximum of 20,000 results to return from the subsearch. The example specifies to limit the duration of the subsearch to 120 seconds. The example also sets a maximum time of 600 seconds (5 minutes) to cache the subsearch results.
 