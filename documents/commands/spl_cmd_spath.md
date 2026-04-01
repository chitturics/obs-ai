---
 command: spath
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/spath
 title: spath
 download_date: 2026-02-03 09:17:46
---

 # spath

The spath command enables you to extract information from the structured data formats XML and JSON. The command stores this information in one or more fields. The command also highlights the syntax in the displayed events list.

You can also use the spath() function with the eval  command. For more information, see the evaluation functions.

spath [input=<field>]  [output=<field>] [path=<datapath> | <datapath>]

#### Optional arguments

The spath command is a distributable streaming command. See Command types.

#### Location path omitted

When used with no path argument, the spath command runs in "auto-extract" mode. By default, when the spath command is in "auto-extract" mode, it finds and extracts all the fields from the first 5,000 characters in the input field. These fields default to _raw if another input source is not specified. If a path is provided, the value of this path is extracted to a field named by the path or to a field specified by the output argument, if the output argument is provided.

#### A location path contains one or more location steps

A location path contains one or more location steps, each of which has a context that is specified by the location steps that precede it. The context for the top-level location step is implicitly the top-level node of the entire XML or JSON document.

#### The location step is composed of a field name and an optional array index

The location step is composed of a field name and an optional array index indicated by curly brackets around an integer or a string.

Array indices mean different things in XML and JSON. For example, JSON uses zero-based indexing. In JSON, product.desc{3} refers to the fourth element of the desc child of the product element. In XML, this same path refers to the third desc child of product.

#### Using wildcards in place of an array index

The spath command lets you use wildcards to take the place of an array index in JSON. Now, you can use the location path entities.hashtags{}.text to get the text for all of the hashtags, as opposed to specifying entities.hashtags{0}.text, entities.hashtags{1}.text, and so on. The referenced path, here entities.hashtags, has to refer to an array for this to make sense. Otherwise, you get an error just like with regular array indices.

This also works with XML. For example, catalog.book and catalog.book{} are equivalent. Both get you all the books in the catalog.

#### Overriding the spath extraction character limit

By default, the spath command extracts all the fields from the first 5,000 characters in the input field. If your events are longer than 5,000 characters and you want to extract all of the fields, you can override the extraction character limit for all searches that use the spath command. To change this character limit for all spath searches, change the extraction_cutoff  setting in the limits.conf file to a larger value.

If you change the default extraction_cutoff  setting, you must also change the setting to the same value in all limits.conf files across all search head and indexer tiers.

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local if you are using *nix, or %SPLUNK_HOME%\etc\system\local if you are using Windows.
- In the [spath] stanza, add the line extraction_cutoff = <value> set to the value you want as the extraction cutoff.
- If your deployment includes search head or indexer clusters, repeat the previous steps on every indexer peer node or search head cluster member. See Use the deployer to distribute apps and configuration updates in Splunk Enterprise Distributed Search and Update common peer configurations and apps in Splunk Enterprise Managing Indexers and Clusters of Indexers for information about changing the limits.conf setting across search head and indexer clusters.

#### JSON data used with the spath command must be well-formed

To use the  spath command to extract JSON data, ensure that the JSON data is well-formed. For example, string literals other than the literal strings true, false and null must be enclosed in double quotation marks ( " ). For a full reference on the JSON data format, see the JSON Data Interchange Syntax standard at https://www.ecma-international.org/publications-and-standards/standards/ecma-404/.

#### Alternatives to the spath command

If you are using autokv or index-time field extractions, the path extractions are performed for you at index time.

You do not need to explicitly use the  spath command  to provide a path.

If you are using indexed_extractions=JSON or KV_MODE=JSON in the props.conf file, then you don't need to use the  spath command.

#### 1. Specify an output field and path

This example shows how to specify an output field and path.

#### 2. Specify just the <datapath>

For the path argument, you can specify the location path with or without the path=. In this example the <datapath> is server.name.

#### 3. Specify an output field and path based on an array

For example, you have this array.

To specify the output field and path, use this syntax.

#### 4. Specify an output field and a path that uses a nested array

For example, you have this nested array.

To specify the output and path from this nested array, use this syntax.

#### 5. Specify the output field and a path for an XML attribute

Use the @ symbol to specify an XML attribute.  Consider the following XML list of books and authors.

Use this search to return the path for the book and the year it was published.

In this example, the output is a single multivalue result that lists all of the years the books were published.

#### 1: GitHub

As an administrator of a number of large Git repositories, you want to:

- See who has committed the most changes and to which repository
- Produce a list of the commits submitted for each user

Suppose you are Indexing JSON data using the GitHub PushEvent webhook. You can use the spath command to extract fields called repository, commit_author, and commit_id:

To see who has committed the most changes to a repository, run the search.

To see the list of commits by each user, run this search.

#### 2: Extract a subset of a XML attribute

This example shows how to extract values from XML attributes and elements.

To extract the values of the locDesc elements (Precios, Prix, Preise, etc.), use:

To extract the value of the locale attribute (es, fr, de, etc.), use:

To extract the attribute of the 4th locDesc (ca), use:

#### 3: Extract and expand JSON events with multi-valued fields

The mvexpand command only works on one multivalued field. This example walks through how to expand a JSON event that has more than one multivalued field into individual events for each field value. For example, given this event with sourcetype=json:

First, start with a search to extract the fields from the JSON. Because no path argument is specified, 
the spath command runs in "auto-extract" mode and extracts all of the fields from the first 5,000 characters in the input field.  The fields are then renamed and placed in a table.

Then, use the eval function, mvzip(), to create a new multivalued field named x, with the values of the size and data:

Now, use the mvexpand command to create individual events based on x and the eval function mvindex() to redefine the values for data and size.

extract, kvform, multikv, regex, rex, xmlkv,
xpath
 