---
 command: search
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/search
 title: search
 download_date: 2026-02-03 09:16:22
---

 # search

Use the search command to retrieve events from indexes or filter the results of a previous search command in the pipeline. You can retrieve events from your indexes, using keywords, quoted phrases, wildcards, and field-value expressions. The search command is implied at the beginning of any search. You do not need to specify the search command at the beginning of your search criteria.

You can also use the search command later in the search pipeline to filter the results from the previous command in the pipeline.

The search command can also be used in a subsearch. See about subsearches in the Search Manual.

After you retrieve events, you can apply commands to transform, filter, and report on the events. Use the vertical bar ( | ) , or pipe character, to apply a command to the retrieved events.

The search command supports IPv4 and IPv6 addresses and subnets that use CIDR notation.

search <logical-expression>

#### Required arguments

#### Logical expression options

#### Comparison expression options

#### Index expression options

#### Time options

For a list of time modifiers, see Time modifiers for search.

The search command is an event-generating command when it is the first command in the search, before the first pipe. When the search command is used further down the pipeline, it is a distributable streaming command. See Command types.

A subsearch can be initiated through a search command such as the search command. See Initiating subsearches with search commands in the Splunk Cloud Platform Search Manual.

#### The implied search command

The search command is implied at the beginning of every search.

When search is the first command in the search, you can use terms such as keywords, phrases, fields, boolean expressions, and comparison expressions to specify exactly which events you want to retrieve from Splunk indexes. If you don't specify a field, the search looks for the terms in the the _raw field.

Some examples of search terms are:

- keywords:	error login, which is the same as specifying for error AND login
- quoted phrases:	"database error"
- boolean operators:	login NOT (error OR fail)
- wildcards:    fail*
- field-value pairs:	status=404, status!=404, or status>200

Note: To search field values that are SPL operators or keywords, such as country=IN, country=AS, iso=AND, or state=OR, you must enclose the operator or keyword in quotation marks. For example: country="IN".

See Use the search command in the Search Manual.

#### Using the search command later in the search pipeline

In addition to the implied search command at the beginning of all searches, you can use the search command later in the search pipeline. The search terms that you can use depend on which fields are passed into the search command.

If the _raw field is passed into the search command, you can use the same types of search terms as you can when the search command is the first command in a search.

However, if the _raw field is not passed into the search command, you must specify field-values pairs that match the fields passed into the search command. Transforming commands, such as stats and chart, do not pass the _raw field to the next command in the pipeline.

#### Boolean expressions

The order in which Boolean expressions are evaluated with the search command is:

- Expressions within parentheses
- NOT clauses
- OR clauses
- AND clauses

This evaluation order is different than the order used with the eval and where commands, which evaluate AND before OR clauses. The search command doesn't support XOR.

See Boolean expressions with logical operators in the Splunk platform Search Manual.

#### Comparing two fields

To compare two fields, do not specify index=myindex fieldA=fieldB or index=myindex fieldA!=fieldB with the search command. When specifying a comparison_expression, the search command expects a <field> compared with a <value>.  The search command interprets fieldB as the value, and not as the name of a field.

Use the where command to compare two fields.

#### Filter using the IN operator

Use the IN operator when you want to determine if a field contains one of several values.

When used with the search command, you can use a wildcard character ( * ) in the list of values for the IN operator. For example:

You can use the NOT operator with the IN operator. For example:

There is also an IN function that you can use with the eval and where commands. Wild card characters are not allowed in the values list when the IN function is used with the eval and where commands. See Comparison and Conditional functions.

#### CIDR matching

The search command can perform a CIDR match on a field that contains IPv4 and IPv6 addresses.

Suppose the ip field contains these values:

If you specify ip="10.10.10.0/24", the search returns the events with the first and last values: 10.10.10.12 and 10.10.10.23.

#### Lexicographical order

Lexicographical order sorts items based on the values used to encode the items in computer memory. In Splunk software, this is almost always UTF-8 encoding, which is a superset of ASCII.

- Numbers are sorted before letters. Numbers are sorted based on the first digit. For example, the numbers 10, 9, 70, 100 are sorted lexicographically as 10, 100, 70, 9.
- Uppercase letters are sorted before lowercase letters.
- Symbols are not standard. Some symbols are sorted before numeric values. Other symbols are sorted before or after letters.

You can specify a custom sort order that overrides the lexicographical order. See the blog Order Up! Custom Sort Orders.

#### Quotes and escaping characters

In general, you need quotation marks around phrases and field values that include white spaces, commas, pipes, quotations, and brackets. Quotation marks must be balanced. An opening quotation must be followed by an unescaped closing quotation. For example:

- A search such as error | stats count will find the number of events containing the string error.
- A search such as ... | search "error | stats count" would return the raw events containing error, a pipe, stats, and count, in that order.

Additionally, use quotation marks around keywords and phrases if you don't want to search for their default meaning, such as Boolean operators and field/value pairs. For example:

- A search for the keyword AND without meaning the Boolean operator: error "AND"
- A search for this field/value phrase: error "startswith=foo"

- The sequence \| as part of a search sends a pipe character to the command, instead of using the pipe as a split between commands.
- The sequence \" sends a literal quotation mark to the command. For example, this is useful if you want to search for a literal quotation mark or insert a literal quotation mark into a field using regular expressions.
- The \\ sequence sends a literal backslash to the command.

- For example, \s in a search string is available as \s to the command, because \s is not a known escape sequence.
- However, the search string \\s is available as \s to the command, because \\ is a known escape sequence that is converted to \.

See Backslashes in the Search Manual.

#### Search with TERM()

You can use the TERM() directive to force Splunk software to match whatever is inside the parentheses as a single term in the index. TERM is more useful when the term contains minor segmenters, such as periods, and is bounded by major segmenters, such as spaces or commas. In fact, TERM does not work for terms that are not bounded by major breakers.

See Use CASE and TERM to match phrases in the Search Manual.

#### Search with CASE()

You can use the CASE() directive to search for terms and field values that are case-sensitive.

See Use CASE and TERM to match phrases in the Search Manual.

These examples demonstrate how to use the search command. You can find more examples in the Start Searching topic of the Search Tutorial.

#### 1. Field-value pair matching

This example demonstrates field-value pair matching for specific values of source IP (src) and destination IP (dst).

#### 2. Using boolean and comparison operators

This example demonstrates field-value pair matching with boolean and comparison operators. Search for events with code values of either 10 or 29, and any host that isn't "localhost", and an xqp value that is greater than 5.

In this example you could also use the IN operator since you are specifying two field-value pairs on the same field.  The revised search is:

#### 3. Using wildcards

This example demonstrates field-value pair matching with wildcards. Search for events from all the web servers that have an HTTP client or server error status.

In this example you could also use the IN operator since you are specifying two field-value pairs on the same field. The revised search is:

#### 4. Using the IN operator

This example shows how to use the IN operator to specify a list of field-value pair matchings. In the events from an access.log file, search the action field for the values addtocart or purchase.

#### 5. Specifying a secondary search

This example uses the search command twice. The search command is implied at the beginning of every search with the criteria eventtype=web-traffic. The search command is used again later in the search pipeline to filter out the results. This search defines a web session using the transaction command and searches for the user sessions that contain more than three events.

#### 6. Using the NOT or != comparisons

Searching with the boolean "NOT"comparison operator is not the same as using the "!=" comparison.

The following search returns everything except fieldA="value2", including all other fields.

The following search returns events where fieldA exists and does not have the value "value2".

If you use a wildcard for the value, NOT fieldA=* returns events where fieldA is null or undefined, and fieldA!=* never returns any events.

See Difference between NOT and != in the Search Manual.

#### 7. Using search to perform CIDR matching

You can use the search command to match IPv4 and IPv6 addresses and subnets that use CIDR notation. For example, this search identifies whether the specified IPv4 address is located in the subnet.

The IP address is located in the subnet, so search displays it in the search results, which look like this.

| time | ip |
| --- | --- |
| 2020-11-19 16:43:31 | 192.0.2.56 |

Note that you can get identical results using the eval command with the cidrmatch("X",Y) function, as shown in this example.

Alternatively, if you're using  IPv6 addresses, you can use the search command to identify whether the specified IPv6 address is located in the subnet.

The IP address is in the subnet, so the search results look like this.

| time | ip |
| --- | --- |
| 2020-11-19 16:43:31 | 2001:0db8:ffff:ffff:ffff:ffff:ffff:ff99 |

#### See also
 