---
 command: xyseries
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/xyseries
 title: xyseries
 download_date: 2026-02-03 09:21:34
---

 # xyseries

This topic walks through how to use the xyseries command.

Converts results into a tabular format that is suitable for graphing. This command is the inverse of the untable command.

xyseries [grouped=<bool>] <x-field> <y-name-field> <y-data-field>... [sep=<string>] [format=<string>]

#### Required arguments

#### Optional arguments

The xyseries command is a distributable streaming command, unless grouped=true is specified and then 
the xyseries command is a transforming command. See Command types.

#### Alias

The alias for the xyseries command is maketable.

#### Results with duplicate field values

When you use the xyseries command to converts results into a tabular format, results that contain duplicate values are removed.

You can use the streamstats command create unique record numbers and use those numbers to retain all results. For an example, see the Extended example for the  untable command.

Let's walk through an example to learn how to reformat search results with the xyseries command.

#### Write a search

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Run this search in the search and reporting app:

The top command automatically adds the count and percent fields to the results. For each categoryId, there are two values, the count and the percent.

The search results look like this:

| categoryId | count | percent |
| --- | --- | --- |
| STRATEGY | 806 | 30.495649 |
| ARCADE | 493 | 18.653046 |
| TEE | 367 | 13.885736 |
| ACCESSORIES | 348 | 13.166856 |
| SIMULATION | 246 | 9.307605 |
| SHOOTER | 245 | 9.269769 |
| SPORTS | 138 | 5.221339 |

#### Identify your fields in the xyseries command syntax

In this example:

- <x-field> = categoryId
- <y-name-field> = count
- <y-data-field> = percent

#### Reformat search results with xyseries

When you apply the xyseries command, the  categoryId serves as the  <x-field> in your search results. The results of the calculation count become the columns, <y-name-field>, in your search results. The <y-data-field>, percent, corresponds to the values in your search results.

Run this search in the search and reporting app:

The search results look like this:

| categoryId | 138 | 245 | 246 | 348 | 367 | 493 | 806 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPORTS | 5.221339 |  |  |  |  |  |  |
| ACCESSORIES |  |  |  | 13.166856 |  |  |  |
| ARCADE |  |  |  |  |  | 18.653046 |  |
| SHOOTER |  | 9.269769 |  |  |  |  |  |
| SIMULATION |  |  | 9.307605 |  |  |  |  |
| STRATEGY |  |  |  |  |  |  | 30.495649 |
| TEE |  |  |  |  |  | 13.885736 |  |

Let's walk through an example to learn how to add optional arguments to the xyseries command.

#### Write a search

To add the optional arguments of the xyseries command, you need to write a search that includes a split-by-field command for multiple aggregates. Use the sep and format arguments to modify the output field names in your search results.

Run this search in the search and reporting app:

This search sorts referrer domain, count(host) and count(productId) by clientIp.

Run this search in the search and reporting app:

In this example:

- <x-field> = clientip
- <y-name-field> = referrer domain
- <y-data-field> = host, productId

The xyseries command needs two aggregates, in this example they are: count(host) count(productId). The first few search results look like this:

#### Add optional argument: sep

Add a string to the sep argument to change the default character that separates the <y-name-field> host,and the <y-data-field> productId. The format argument adds the <y-name-field> and separates the field name and field value by the default ":"

Run this search in the search and reporting app:

The first few search results look like this:

#### Add optional argument: format

The format argument adds the <y-name-field> and separates the field name and field value by the default ":" For example, the default for this example looks like count(host):referrer_domain

When you specify a string to separate the <y-name-field> and <y-data-field> with the format argument, it overrides any assignment from the sep argument. In the following example, the sep argument assigns the "-" character to separate the <y-name-field> and <y-data-field> fields. The format argument assigns a "+" and this assignment takes precedence over sep. In this case $VAL$  and $AGG$ represent both the <y-name-field> and <y-data-field>. As seen in the search results, the <y-name-field>, host, and <y-data-field>, productId can correspond to either $VAL$ or $AGG$.

Run this search in the search and reporting app:

The first few search results look like this:

#### Add optional argument: grouped

The grouped argument determines whether the xyseries command runs as a distributable streaming command, or a transforming command. The default state grouped=FALSE for the xyseries command runs as a streaming command.
 