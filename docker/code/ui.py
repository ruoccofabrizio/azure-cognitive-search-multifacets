import streamlit as st
import pandas as pd
from urllib.error import URLError
import requests
from pprint import pprint
import os
from collections import Counter
from copy import copy

os.environ['search_service'] = ''
os.environ['index_name'] = 'multifacets'
os.environ['api_version'] = '2021-04-30-Preview'
os.environ['api_key'] = ''
os.environ['facets'] = 'brand,vendor,category'
os.environ['top'] = 1000
top = os.environ['top']

# Function called when pushing on a filter button in the UI
def push_filter(checkbox_key):
    # Get facet and value from filter
    facet = checkbox_key.split('$')[1]
    value = checkbox_key.split('$')[2].split('#')[0]
    count = checkbox_key.split('$')[2].split('#')[1]

    # if facet is not in active filters add the filter
    if facet not in list(map(lambda x: x['facet'], st.session_state['filters'])):
        st.session_state['filters'].append({"facet": facet, "value": [value], "count": int(count)})
    else:
        # if the facet is already in the active filter, retrieve the item in the filter list
        filt = list(filter(lambda x: x['facet'] == facet, st.session_state['filters']))[0]
        # if the value for the facet is already in the active filters, remove it (this happens when in the UI you deselect the filter)
        if value in filt['value']:
            filt['value'].remove(value)
            # if all the values for the specific facet are removed, remove the filter as well from the active filters
            if filt['value'] == []:
                st.session_state['filters'] = list(filter(lambda x: x['facet'] != facet, st.session_state['filters']))
        # if the value is not in the active filters list, add it
        else:
            filt['value'].append(value)
            filt['count'] += int(count)
            # if the facet is in the list for remotely computes on Azure Cognitive Search, throw a new query to get a new result set
            if filt['facet'] in st.session_state['exclude']:
                # print('NEED TO SEND A NEW QUERY')
                st.session_state['send_new_query'] = True
                st.session_state['exclude'] = [filt['facet']]


# Send query to Azure Cognitive Search
def send_query(search= "*"):
    # Evalute if you need to issue a new query to Search Engine or work with session data 
    # Here you can also add considerations on the number of items in the result to issue other queries for faceting if needed
    if st.session_state['local_query']['query'] != search or st.session_state['local_query']['results']['@odata.count'] > top or st.session_state['send_new_query']:
        print("Sending query to ACS")

        # Search URL
        url = f"https://{os.environ['search_service']}.search.windows.net/indexes/{os.environ['index_name']}/docs/search?api-version={os.environ['api_version']}"
        # Required authentication headers
        headers = {
            "content-type" : "application/json",
            "api-key" : os.getenv('api_key')
        }
        # Compute facet with Azure Cognitive Search format
        facets = {x : f"{x},count:50" for x in os.environ['facets'].replace(' ','').split(',')}
        facets = [v for k,v in facets.items()]

        # Store the search query in the Session Store
        st.session_state['local_query']['query'] = search

        # Create the full query with boosting of selected facets 
        # ONLY needed when your results set is over 1K (or defined tops) docs
        full_search = f"({search})"
        # if a new query has to be submitted, reset the exclusion for local facet computing
        st.session_state['exclude'] = [] if not st.session_state['send_new_query'] else st.session_state['exclude'] 
        # if locally stored result set has more items than 1K (or defined tops) docs, create a dynamic boost to push on top the item with selected facet
        if st.session_state['local_query'].get('results') != None:
            if st.session_state['local_query']['results'].get('@odata.count', 0) > top or st.session_state['send_new_query']:
                # print(f"filters: {st.session_state['filters']}")
                for f in st.session_state['filters']:
                    if not st.session_state['send_new_query']:
                        st.session_state['exclude'].append(f['facet'])
                    search_filters = " OR ".join(list(map(lambda x: f"{f['facet']}:{x}^1000", f['value'])))
                    full_search += f" ({search} AND ({search_filters}))" 

        # Create the request body
        body = {
            "search" : full_search,
            "facets" : facets,
            "queryType" : "full",
            "count" : True,
            "top": top
        }
        # Log request body for debugging
        pprint(body)
        # Send request to Azure Cognitive Search
        r = requests.post(url, headers=headers, json=body)
        # Log request status code
        print(r.status_code)
        # Print an error if request fails
        if not r.ok:
            r.text

        # Update Session results with data coming from Azure Cognitive Search
        res = r.json()
        previous = copy(st.session_state['local_query']['results'])
        st.session_state['local_query']['results'] = res

        if previous != {}: #if results are already in the session
            # compute facets locally for all the fields but the excluded (as not part of the local result set)
            res['@search.facets'] = compute_facets(st.session_state['exclude'])

            # filter the new result set to remove all the items not selected by the filter
            for f in st.session_state['filters']:
                res['value'] = list(filter(lambda x: x[f['facet']] in f['value'], res['value']))
            # Count the results locally and override the service data
            res['value'] = st.session_state['local_query']['results']['value']
            res['@odata.count'] = len(st.session_state['local_query']['results']['value'])

        # Set new query to false as the results set is saved locally for further filtering
        st.session_state['send_new_query'] = False

    else:
        print("Local facetings")
        res = copy(st.session_state['local_query']['results'])        
        results = copy(st.session_state['local_query']['results'])['value']
        
        # Apply active filters on the result set
        for f in st.session_state['filters']:
            results = list(filter(lambda x: x[f['facet']] in f['value'], results))

        # Overwrite new results, facets and result lenght for visualization
        res['value'] = results
        res['@search.facets'] = compute_facets(st.session_state['exclude'])
        res['@odata.count'] = len(results)
        
    return res

# Locally compute the search facets
def compute_facets(exclude=[]):
    search_facets = {}
    search_facets_output = {}
    facets = os.environ['facets'].replace(' ','').split(',')
    # check if any facet has to be compute on server side
    if len(exclude) > 0:
        print("Getting remote facet")
        remote_facets_output = query_facets(search, exclude)
    # For each facet count the docs applying all filters but those on the facet itself, starting from the full result set
    for facet in facets:
        if facet not in exclude:
            search_facets[facet] = copy(st.session_state['local_query']['results'])['value']
            for f in st.session_state['filters']:
                if f['facet'] != facet: # Exclude the filter on the facet you are computing the counter
                    search_facets[facet] = list(filter(lambda x: x[f['facet']] in f['value'] , search_facets[facet]))
            # Count all the values and re-format in the ['@search.facets'] format
            search_facets_output[facet] = []
            for k,v in Counter(list(map(lambda x: x[facet], search_facets[facet]))).items():
                search_facets_output[facet].append({"count": v, "value": k})
            search_facets_output[facet] = sorted(search_facets_output[facet], key= lambda x: x['count'], reverse=True)
        else:
            search_facets_output[facet] = remote_facets_output[facet]
    return search_facets_output
        

def query_facets(search, exclude):
    print("Query for facets")
    url = f"https://{os.environ['search_service']}.search.windows.net/indexes/{os.environ['index_name']}/docs/search?api-version={os.environ['api_version']}"
    # Required authentication headers
    headers = {
        "content-type" : "application/json",
        "api-key" : os.getenv('api_key')
    }
    # Compute facet with Azure Cognitive Search format
    facets = {x : f"{x},count:50" for x in exclude}#.replace(' ','').split(',')}
    facets = [v for k,v in facets.items()]

    # Create filter for facet retrieval on Azure Cognitive Search
    odata_filter = ""
    for f in st.session_state['filters']:
        if f['facet'] not in exclude:#replace(' ','').split(','):
            filter_values = ",".join(list(map(lambda x: f"{x}", f['value'])))
            odata_filter += ' and ' if odata_filter != "" else ''
            odata_filter += f"search.in({f['facet']}, '{filter_values}')"

    # print(odata_filter)

    # Create the request body
    body = {
        "search" : search,
        "facets" : facets,
        "queryType" : "full",
        "count" : True,
        "top": top,
        "select": 'id',
        "filter" : odata_filter
    }

    # Log request body for debugging
    pprint(body)
    # Send request to Azure Cognitive Search
    r = requests.post(url, headers=headers, json=body)
    # Log request status code
    print(r.status_code)
    # Print an error if request fails
    if not r.ok:
        r.text

    return r.json()['@search.facets']


# Add facet on the sidebar
def add_facet(facet):
    # Write facet name
    st.sidebar.write(facet.capitalize())
    # Read facet value from the last query if available
    facet_values = []
    if r.get('@search.facets') != None and r.get('@search.facets').get(facet) != None:
        facet_values = r.get('@search.facets').get(facet)

    # Extract all the filter already active in the UI for rendering them as selected
    active_filters = list(filter(None,map(lambda x: x['value'] if x['facet'] == facet else None, st.session_state['filters'])))
    active_filters = active_filters[0] if len(active_filters) > 0 else []
    # Draw all the facet buttons in the UI and define the callback function
    for f in facet_values:
        st.sidebar.checkbox(f['value'] + ' (' + str(f['count']) +')' ,
            on_change=push_filter, 
            value= True if f['value'] in active_filters else False,
            kwargs={"checkbox_key" : f"facet${facet}${f['value']}#{f['count']}"}
            )

# MAIN 
try:
    # Define search bar and default search value
    default = "jeans"
    search = st.text_input("Search Query", default)

    # Create a Session variable collecting applied filters
    if "filters" not in st.session_state:
        st.session_state['filters'] = []  
    # Create a Session variable to use local data when the query does not change
    if "local_query" not in st.session_state:
        st.session_state['local_query'] = {
            "query": "",
            "results": {}
        }
    # Create a Session variable to control when to submit a new query to Azure Cognitive Search
    if "send_new_query" not in st.session_state:
        st.session_state['send_new_query'] = True
    # Create a Session variable to store facets that have to be compute on Azure Cognitive Search
    if "exclude" not in st.session_state:
        st.session_state['exclude'] = []
    

    # Send Query to Azure Cognitive Search
    r = send_query(search=search)
    # Add facets for configured fields
    for f in os.environ['facets'].replace(' ','').split(','):
        add_facet(f)

    # Show query results and count
    st.write(f"Results count: {r['@odata.count']}")
    search_res = pd.DataFrame(r['value'])
    search_res.index = search_res.index +1 # Just for visualization re-index the Pandas dataframe
    search_res

except URLError as e:
    st.error(
        """
        **This demo requires internet access.**

        Connection error: %s
        """
        % e.reason
    )

