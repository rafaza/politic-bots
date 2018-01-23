from collections import defaultdict
from datetime import datetime
from db_manager import DBManager
import logging
import networkx as net

logging.basicConfig(filename='politic_bots.log', level=logging.DEBUG)


class NetworkAnalyzer:
    __dbm_tweets = None
    __dbm_users = None
    __dbm_networks = None
    __network = None
    __graph = None
    __nodes = set()
    __unknown_users = set()
    __node_sizes = None

    def __init__(self):
        self.__dbm_tweets = DBManager('tweets')
        self.__dbm_users = DBManager('users')
        self.__dbm_networks = DBManager('networks')
        self.__network = []

    def __computer_ff_ratio(self, friends, followers):
        if followers > 0 and friends > 0:
            return friends / followers
        else:
            return 0

    def create_users_db(self, clear_collection=False):
        logging.info('Creating database of users, it can take several minutes, please wait_')
        if clear_collection:
            self.__dbm_users.clear_collection()
        users = self.__dbm_tweets.get_unique_users()
        for user in users:
            db_user = {
                'screen_name': user['screen_name'],
                'friends': user['friends'],
                'followers': user['followers'],
                'ff_ratio': self.__computer_ff_ratio(user['friends'], user['followers']),
                'interactions': user['interactions'],
                'tweets': user['tweets_count'],
                'original_tweets': user['original_count'],
                'rts': user['retweets_count'],
                'qts': user['quotes_count'],
                'rps': user['replies_count']
            }
            # Assign the party and movement to the party and movement that are more related to the user
            user_party = self.__dbm_tweets.get_party_user(user['screen_name'])[0]
            db_user.update({'party': user_party['partido']})
            if user_party and user_party != '':
                user_movement = self.__dbm_tweets.get_movement_user(user['screen_name'])[0]
                db_user.update({'movement': user_movement['movimiento']})
            else:
                db_user.update({'movement': ''})
            filter_query = {'screen_name': user['screen_name']}
            self.__dbm_users.update_record(filter_query, db_user, create_if_doesnt_exist=True)

    def generate_network(self, subnet_query={}, depth=1, file_name='network'):
        net_query = subnet_query.copy()
        net_query.update({'depth': depth})
        ret_net = self.__dbm_networks.search(net_query)
        # the net doesn't exist yet, let's create it
        if ret_net.count() == 0:
            logging.info('Generating the network, it can take several minutes, please wait_')
            users = self.__dbm_users.search(subnet_query)
            # for each user generate his/her edges
            for user in users:
                self.__nodes.add(tuple({'screen_name': user['screen_name'], 'party': user['party'],
                                        'movement': user['movement'], 'ff_ratio': user['ff_ratio']}.items()))
                for interacted_user, interactions in user['interactions'].items():
                    iuser = self.__dbm_users.find_record({'screen_name': interacted_user})
                    if not iuser:
                        if depth > 1:
                            iuser_ffratio = self.__get_ffratio(interacted_user)
                            if not iuser_ffratio:
                                self.__unknown_users.add(interacted_user)
                                continue
                        else:
                            self.__unknown_users.add(interacted_user)
                            continue
                    else:
                        iuser_ffratio = iuser['ff_ratio']
                    self.__nodes.add(tuple({'screen_name': iuser['screen_name'], 'party': iuser['party'],
                                     'movement': iuser['movement'], 'ff_ratio': iuser['ff_ratio']}.items()))
                    edge = {
                        'nodeA': {'screen_name': user['screen_name'], 'ff_ratio': user['ff_ratio'],
                                  'party': user['party'], 'movement': user['movement']},
                        'nodeB': {'screen_name': interacted_user, 'ff_ratio': iuser_ffratio,
                                  'party': user['party'], 'movement': user['movement']},
                        'weight': interactions['total']
                    }
                    self.__network.append(edge)
            logging.info('Created a network of {0} nodes and {1} edges'.format(len(self.__nodes), len(self.__network)))
            logging.info('Unknown users {0}'.format(len(self.__unknown_users)))
            # save the net in a gefx file for posterior usage
            f_name = self.save_network_in_gexf_format(file_name)
            logging.info('Saved the network in the file {0}'.format(f_name))
            db_net = {'file_name': f_name}
            db_net.update(net_query)
            self.__dbm_networks.save_record(db_net)
        else:
            f_net = ret_net[0]
            logging.info('The network was already generated, please find it at {0}'.format(f_net['file_name']))

    def create_graph(self):
        logging.info('Creating the graph, please wait_')
        self.__graph = net.DiGraph()
        ff_ratio = defaultdict(lambda: 0.0)
        # create a directed graph from the edge data and populate a dictionary
        # with the friends/followers ratio
        for edge in self.__network:
            user = edge['nodeA']['screen_name']
            interacted_with = edge['nodeB']['screen_name']
            num_interactions = edge['weight']
            u_ff_ratio = edge['nodeA']['ff_ratio']
            self.__graph.add_edge(user, interacted_with, weight=int(num_interactions))
            ff_ratio[user] = float(u_ff_ratio)
        # obtain central node
        # degrees = net.degree(self.__graph)
        # central_node, max_degree = sorted(degrees, key=itemgetter(1))[-1]
        # center the graph around the central node
        # ego_graph = net.DiGraph(net.ego_graph(self.__graph, central_node))
        return

    def get_graph_nodes(self):
        return len(self.__nodes)

    def get_graph_edges(self):
        return len(self.__network)

    def get_graph(self):
        return self.__graph

    def get_node_sizes(self):
        return self.__node_sizes

    def __get_ffratio(self, screen_name):
        query = {
            '$or': [
                {'tweet_obj.user.screen_name': screen_name},
                {'tweet_obj.retweeted_status.user.screen_name': screen_name},
                {'tweet_obj.quoted_status.user.screen_name': screen_name}
            ]
        }
        tweet_obj = self.__dbm_tweets.find_record(query)
        if tweet_obj:
            tweet = tweet_obj['tweet_obj']
            if 'retweeted_status' in tweet.keys():
                return self.__computer_ff_ratio(tweet['retweeted_status']['user']['friends_count'],
                                                tweet['retweeted_status']['user']['followers_count'])
            elif 'quoted_status' in tweet.keys():
                return self.__computer_ff_ratio(tweet['quoted_status']['user']['friends_count'],
                                                tweet['quoted_status']['user']['followers_count'])
            else:
                return self.__computer_ff_ratio(tweet['user']['friends_count'],
                                                tweet['user']['followers_count'])
        else:
            return None

    def save_network_in_gexf_format(self, file_name):
        today = datetime.strftime(datetime.now(), '%m/%d/%y')
        f_name = 'gefx/'+file_name+'.gexf'
        with open(f_name, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<gexf xmlns="http://www.gexf.net/1.2draft" xmlns:viz="http://www.gexf.net/1.1draft/viz" '
                    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                    'xsi:schemaLocation="http://www.gexf.net/1.2draft http://www.gexf.net/1.2draft/gexf.xsd" '
                    'version="1.2">\n')
            f.write('<meta lastmodifieddate="{0}">\n'.format(today))
            f.write('<creator>PoliticBots</creator>\n')
            f.write('<description>{0}</description>\n'.format(file_name))
            f.write('</meta>\n')
            f.write('<graph mode="static" defaultedgetype="directed">\n')
            # add data attributes
            f.write('<attributes class="node">\n')
            f.write('<attribute id="0" title="party" type="string"/>\n')
            f.write('<attribute id="1" title="movement" type="string"/>\n')
            f.write('<attribute id="2" title="ff_ratio" type="float"/>\n')
            f.write('</attributes>\n')
            # add nodes
            f.write('<nodes>\n')
            node_id = 0
            list_nodes = []
            for node_tup in self.__nodes:
                node = dict(node_tup)
                f.write('<node id="{0}" label="{1}">\n'.format(node_id, node['screen_name']))
                f.write('<attvalues>\n')
                f.write('<attvalue for="0" value="{}"/>\n'.format(node['party']))
                f.write('<attvalue for="1" value="{}"/>\n'.format(node['movement']))
                f.write('<attvalue for="2" value="{}"/>\n'.format(node['ff_ratio']))
                f.write('</attvalues>\n')
                #f.write('<viz:size value="{0}"/>\n'.format(node['ff_ratio']))
                f.write('</node>\n')
                node_id += 1
                list_nodes.append(node['screen_name'])
            f.write('</nodes>\n')
            # add edges
            f.write('<edges>\n')
            edge_id = 0
            for edge in list(self.__network):
                id_vertexA = list_nodes.index(edge['nodeA']['screen_name'])
                id_vertexB = list_nodes.index(edge['nodeB']['screen_name'])
                weight = edge['weight']
                f.write('<edge id="{0}" source="{1}" target="{2}" weight="{3}"/>\n'.format(edge_id, id_vertexA,
                                                                                           id_vertexB, weight))
                edge_id += 1
            f.write('</edges>\n')
            f.write('</graph>\n')
            f.write('</gexf>\n')
        return f_name
