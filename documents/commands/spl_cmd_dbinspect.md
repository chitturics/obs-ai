---
 command: dbinspect
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/dbinspect
 title: dbinspect
 download_date: 2026-02-03 09:04:23
---

 # dbinspect

Returns information about the buckets in the specified index. If you are using Splunk Enterprise, this command helps you understand where your data resides so you can optimize disk usage as required. Searches on an indexer cluster return results from the primary buckets and replicated copies on other peer nodes.

The Splunk index is the repository for data ingested by Splunk software. As incoming data is  indexed and transformed into events, Splunk software creates files of rawdata and metadata (index files). The files reside in sets of directories organized by age. These directories are called  buckets.

For more information, see Indexes, indexers, and clusters and How the indexer stores indexes in Managing Indexers and Clusters of Indexers.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Time scale units

These are options for specifying a timescale as the bucket span.

#### Information returned when no span is specified

When you invoke the dbinspect command without the span argument, the following information about the buckets in the index is returned.

| Field name | Description |
| --- | --- |
| bucketId | A string comprised of <index>~<id>~<guId>, where the delimiters are tilde characters. For example, summary~2~4491025B-8E6D-48DA-A90E-89AC3CF2CE80. |
| endEpoch | The timestamp for the last event in the bucket, which is the time-edge of the bucket furthest towards the future. Specify the timestamp in the number of seconds from the UNIX epoch. |
| eventCount | The number of events in the bucket. |
| guId | The globally unique identifier (GUID) of the server that hosts the index. This is relevant for index replication. |
| hostCount | The number of unique hosts in the bucket. |
| id | The local ID number of the bucket, generated on the indexer on which the bucket originated. |
| index | The name of the index specified in your search. You can specify index=* to inspect all of the indexes, and the index field will vary accordingly. |
| modTime | The timestamp for the last time the bucket was modified or updated, in a format specified by the timeformat flag. |
| path | The location to the bucket. The naming convention for the bucket path varies slightly, depending on whether the bucket rolled to warm while its indexer was functioning as a cluster peer:
For non-clustered buckets: db_<newest_time>_<oldest_time>_<localid>For clustered original bucket copies: db_<newest_time>_<oldest_time>_<localid>_<guid>For clustered replicated bucket copies: rb_<newest_time>_<oldest_time>_<localid>_<guid>
For more information, read "How Splunk stores indexes" and "Basic cluster architecture" in Managing Indexers and Clusters of Indexers. |
| rawSize | The volume in bytes of the raw data files in each bucket. This value represents the volume before compression and the addition of index files. |
| sizeOnDiskMB | The size in MB of disk space that the bucket takes up expressed as a floating point number. This value represents the volume of the compressed raw data files and the index files. |
| sourceCount | The number of unique sources in the bucket. |
| sourceTypeCount | The number of unique sourcetypes in the bucket. |
| splunk_server | The name of the Splunk server that hosts the index in a distributed environment. |
| startEpoch | The timestamp for the first event in the bucket (the time-edge of the bucket furthest towards the past), in number of seconds from the UNIX epoch. |
| state | Specifies whether the bucket is warm, hot, cold. |
| tsidxState | Specifies whether each bucket contains full-size or reduced tsidx files. If the value of this field in the results is full, the tsidx files are full-size. If the value is mini, the tsidx files are reduced. See Determine whether a bucket is reduced in Splunk Enterprise Managing Indexers and Clusters of Indexers. |
| corruptReason | Specifies the reason why the bucket is corrupt. The corruptReason field appears only when  corruptonly=true. |

The dbinspect command is a generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

#### Accessing data and security

If no data is returned from the index that you specify with the  dbinspect command, it is possible that you do not have the authorization to access that index. The ability to access data in the Splunk indexes is controlled by the authorizations given to each role.  See Use access control to secure Splunk data in Securing Splunk Enterprise.

#### Non-searchable bucket copies

For hot non-searchable bucket copies on target peers, tsidx and other metadata files are not maintained. Because accurate information cannot be reported, the following fields show NULL:

- eventCount
- hostCount
- sourceCount
- sourceTypeCount
- startEpoch
- endEpoch

#### 1. CLI use of the dbinspect command

Display a chart with the span size of 1 day, using the command line interface (CLI).

The results look like this:

#### 2. Default dbinspect output

Default dbinspect output for a local _internal index.

The results look like this:

This screen shot does not display all of the columns in the output table. On your computer, scroll to the right to see the other columns.

#### 3. Check for corrupt buckets

Use the corruptonly argument to display information about corrupted buckets, instead of information about all buckets. The output fields that display are the same with or without the corruptonly argument.

#### 4. Count the number of buckets for each Splunk server

Use this command to verify that the Splunk servers in your distributed environment are included in the dbinspect command. Counts the number of buckets for each server.

#### 5. Find the index size of buckets in GB

Use dbinspect to find the index size of buckets in GB. For current numbers, run this search over a recent time range.

#### 6. Determine whether a bucket is reduced

Run the dbinspect search command:

If the value of the tsidxState field for each bucket is full, the tsidx files are full-size. If the value is mini, the tsidx files are reduced.
 