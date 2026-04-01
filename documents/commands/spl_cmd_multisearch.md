---
 command: multisearch
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/multisearch
 title: multisearch
 download_date: 2026-02-03 09:12:18
---

 # multisearch

The multisearch command is a generating command that runs multiple streaming searches at the same time. This command requires at least two subsearches and allows only streaming operations in each subsearch. Examples of streaming searches include searches with the following commands: search, eval, where, fields, and rex. For more information, see  Types of commands in the Search Manual.

| multisearch <subsearch1> <subsearch2> <subsearch3> ...

#### Required arguments

The multisearch command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

#### The multisearch command doesn't support peer selection

You can't exclude search peers from multisearch searches because the multisearch command connects to all peers by default. For example, the following multisearch search connects to the indexer called myServer even though it is excluded using NOT:

Instead of using the multisearch command to exclude search peers from your search, you can use other commands such as append with search optimization turned off. If you don't turn off search optimization, Splunk software might internally convert the append command to the multisearch command in order to optimize the search and might not exclude the search peers.

You can turn off search optimization for a specific search by including the following command at the end of your search:

For example, the following workaround uses the append command to exclude myServer:

See Optimization settings in the Search Manual.

#### Subsearch processing and limitations

With the multisearch command, the events from each subsearch are interleaved. Therefore the multisearch command is not restricted by the subsearch limitations.

Unlike the append command, the multisearch command does not run the subsearch to completion first.  The following subsearch example with the append command is not the same as using the multisearch command.

#### Example 1:

Search for events from both index a and b. Use the eval command to add different fields to each set of results.

append, join
 