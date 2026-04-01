---
 command: walklex
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/walklex
 title: walklex
 download_date: 2026-02-03 09:20:57
---

 # walklex

Generates a list of terms or indexed fields from each bucket of event indexes.

Watch this Splunk How-To video, Using the Walklex Command, to see a demonstration about how to use this command.

Note: Certain restricted search commands, including mpreview, mstats, tstats, typeahead, and walklex, might stop working if your organization uses field filters to protect sensitive data. See Plan for field filters in your organization in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The walklex command is a  generating command, which use a leading pipe character. The walklex command must be the first command in a search. See Command types.

When the Splunk software indexes event data, it segments each event into raw tokens using rules specified in segmenters.conf file. You might end up with raw tokens that are actually key-value pairs separated by an arbitrary delimiter such as an equal ( = ) symbol.

The following search uses the walklex and where commands to find the raw tokens in your index. It uses the stats command to count the raw tokens.

#### Return only indexed field names

Specify the type=field argument to have walklex return only the field names from indexed fields.

The indexed fields returned by walklex can include default fields such as host, source, sourcetype, the date_* fields, punct, and so on. It can also include additional indexed fields configured as such in props.conf and transforms.conf and created with the INDEXED_EXTRACTIONS setting or other WRITE_META methods. The discovery of this last set of additional indexed fields is likely to help you with accelerating your searches.

#### Return the set of terms that are indexed fields with indexed values

Specify type=fieldvalue argument to have walklex return the set of terms from the index that are indexed fields with indexed values.

The type=fieldvalue argument returns the list terms from the index that are indexed fields with indexed values. Unlike the type=field argument, where the values returned are only the field names themselves, the type=fieldvalue argument returns indexed field names that have any field value.

For example, if the indexed field term is runtime::0.04, the value returned by the type=fieldvalue argument is runtime::0.04. The value returned by the type=field argument is runtime.

#### Return all TSIDX keywords that are not part of an indexed field structure

Specify type=term to have walklex return the keywords from the TSIDX files that are not part of any indexed field structure. In other words, it excludes all indexed field terms of the form <field>::<value>.

#### Return terms of all three types

When you do not specify a type, or when you specify type=all, walklex uses the default type=all argument. This causes walklex to return the terms in the index of all three types: field, fieldvalue, and term.

Note: When you use type=all, the indexed fields are not called out as explicitly as the fields are with the type=field argument. You need to split the term field on :: to obtain the field values from the indexed term.

#### Support for hot buckets

Because the walklex command doesn't work on hot buckets, recently loaded data displays in search results only after buckets have rolled over from hot to warm. You can either wait for buckets of an index to roll over from hot to warm on their own, or you can restart Splunk platform or manually roll the buckets over to warm. See Rolling buckets manually from hot to warm.

#### Restrictions

The walklex command applies only to event indexes. It cannot be used with metrics indexes.

People who have search filters applied to one or more of their roles cannot use walklex unless they also have a role with either the run_walklex capability or the admin_all_objects capability. For more information about role-based search filters, see Create and manage roles with Splunk Web in Securing the Splunk Platform. For more information about role-based capabilities, see Define roles on the Splunk platform with capabilities, in Securing the Splunk Platform.

#### 1. Return the total count for each term in a specific bucket

The following example returns all of the terms in each bucket of the _internal index and finds the total count for each term.

#### 2. Specifying multiple indexes

The following example returns all of the terms that start with foo in each bucket of the _internal and _audit indexes.

#### 3. Use a pattern to locate indexed field terms

The following example returns all of the indexed field terms for each bucket that end with bar in the _internal index.

#### 4. Return all field names of indexed fields

The following example returns all of the field names of indexed fields in each bucket of the _audit index.
 