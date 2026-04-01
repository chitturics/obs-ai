---
 command: arules
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/arules
 title: arules
 download_date: 2026-02-03 09:02:18
---

 # arules

The arules command looks for associative relationships between field values.  The command returns a table with the following columns: Given fields, Implied fields, Strength, Given fields support, and Implied fields support. The given and implied field values are the values of the fields you supply. The Strength value indicates the relationship between (among) the given and implied field values.

Implements the arules algorithm as discussed in Michael Hahsler, Bettina Gruen and Kurt Hornik (2012). arules: Mining Association Rules and Frequent Itemsets. R package version 1.0-12. This algorithm is similar to the algorithms used for online shopping websites which suggest related items based on what items other customers have viewed or purchased.

arules [<arules-option>... ] <field-list>...

#### Required arguments

#### Optional arguments

#### arules options

The arules command is a streaming command that is both distributable streaming and centralized streaming. See Command types.

Example 1: Search for the likelihood that the fields are related.

associate, correlate
 