# Copyright (c) 2006-2010 Mitch Garnaat http://garnaat.org/
# Copyright (c) 2010, Eucalyptus Systems, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#

import xml.sax
import base64
import time
import uuid
import urllib
import boto
from boto.connection import AWSAuthConnection
from boto import handler
from boto.resultset import ResultSet
import boto.jsonresponse
import exception
import hostedzone

HZXML = """<?xml version="1.0" encoding="UTF-8"?>
<CreateHostedZoneRequest xmlns="%(xmlns)s">
  <Name>%(name)s</Name>
  <CallerReference>%(caller_ref)s</CallerReference>
  <HostedZoneConfig>
    <Comment>%(comment)s</Comment>
  </HostedZoneConfig>
</CreateHostedZoneRequest>"""
        
#boto.set_stream_logger('dns')

class Route53Connection(AWSAuthConnection):

    DefaultHost = 'route53.amazonaws.com'
    Version = '2010-10-01'
    XMLNameSpace = 'https://route53.amazonaws.com/doc/2010-10-01/'

    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None,
                 port=None, proxy=None, proxy_port=None,
                 host=DefaultHost, debug=0):
        AWSAuthConnection.__init__(self, host,
                aws_access_key_id, aws_secret_access_key,
                True, port, proxy, proxy_port, debug=debug)

    def add_aws_auth_header(self, headers, method, path):
        if not headers.has_key('Date'):
            headers['Date'] = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                                            time.gmtime())

        if self.hmac_256:
            hmac = self.hmac_256.copy()
            alg = 'HmacSHA256'
        else:
            hmac = self.hmac.copy()
            alg = 'HmacSHA1'

        hmac.update(headers['Date'])
        b64_hmac = base64.encodestring(hmac.digest()).strip()
        s = "AWS3-HTTPS AWSAccessKeyId=%s," % self.aws_access_key_id
        s += "Algorithm=%s,Signature=%s" % (alg, b64_hmac)
        headers['X-Amzn-Authorization'] = s
        
    def make_request(self, action, path, headers=None, data='', params=None):
        if params:
            pairs = []
            for key, val in params.iteritems():
                if val is None: continue
                pairs.append(key + '=' + urllib.quote(str(val)))
            path += '?' + '&'.join(pairs)
        return AWSAuthConnection.make_request(self, action, path, headers, data)

    # Hosted Zones

    def get_all_hosted_zones(self):
        """
        Returns a Python data structure with information about all
        Hosted Zones defined for the AWS account.
        """
        response = self.make_request('GET', '/%s/hostedzone' % self.Version)
        body = response.read()
        boto.log.debug(body)
        if response.status >= 300:
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        e = boto.jsonresponse.Element(list_marker='HostedZones',
                                      item_marker=('HostedZone',))
        h = boto.jsonresponse.XmlHandler(e, None)
        h.parse(body)
        return e
    
    def get_hosted_zone(self, hosted_zone_id):
        """
        Get detailed information about a particular Hosted Zone.
        
        :type hosted_zone_id: str
        :param hosted_zone_id: The unique identifier for the Hosted Zone

        """
        uri = '/%s/hostedzone/%s' % (self.Version, hosted_zone_id)
        response = self.make_request('GET', uri)
        body = response.read()
        boto.log.debug(body)
        if response.status >= 300:
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        e = boto.jsonresponse.Element(list_marker='NameServers',
                                      item_marker=('NameServer',))
        h = boto.jsonresponse.XmlHandler(e, None)
        h.parse(body)
        return e

    def create_hosted_zone(self, domain_name, caller_ref=None, comment=''):
        """
        Create a new Hosted Zone.  Returns a Python data structure with
        information about the newly created Hosted Zone.
        
        :type domain_name: str
        :param domain_name: The name of the domain. This should be a
                            fully-specified domain, and should end with
                            a final period as the last label indication.
                            If you omit the final period, Amazon Route 53
                            assumes the domain is relative to the root.
                            This is the name you have registered with your
                            DNS registrar. It is also the name you will
                            delegate from your registrar to the Amazon
                            Route 53 delegation servers returned in
                            response to this request.A list of strings
                            with the image IDs wanted

        :type caller_ref: str
        :param caller_ref: A unique string that identifies the request
                           and that allows failed CreateHostedZone requests
                           to be retried without the risk of executing the
                           operation twice.
                           If you don't provide a value for this, boto will
                           generate a Type 4 UUID and use that.

        :type comment: str
        :param comment: Any comments you want to include about the hosted
                        zone.

        """
        if caller_ref is None:
            caller_ref = str(uuid.uuid4())
        params = {'name' : domain_name,
                  'caller_ref' : caller_ref,
                  'comment' : comment,
                  'xmlns' : self.XMLNameSpace}
        xml = HZXML % params
        uri = '/%s/hostedzone' % self.Version
        response = self.make_request('POST', uri,
                                     {'Content-Type' : 'text/xml'}, xml)
        body = response.read()
        boto.log.debug(body)
        if response.status == 201:
            e = boto.jsonresponse.Element(list_marker='NameServers',
                                          item_marker=('NameServer',))
            h = boto.jsonresponse.XmlHandler(e, None)
            h.parse(body)
            return e
        else:
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        
    def delete_hosted_zone(self, hosted_zone_id):
        uri = '/%s/hostedzone/%s' % (self.Version, hosted_zone_id)
        response = self.make_request('DELETE', uri)
        body = response.read()
        boto.log.debug(body)
        if response.status not in (200, 204):
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        e = boto.jsonresponse.Element()
        h = boto.jsonresponse.XmlHandler(e, None)
        h.parse(body)
        return e

    # Resource Record Sets

    def get_all_rrsets(self, hosted_zone_id, type=None,
                       name=None, maxitems=None):
        """
        Retrieve the Resource Record Sets defined for this Hosted Zone.
        Returns the raw XML data returned by the Route53 call.
        
        :type hosted_zone_id: str
        :param hosted_zone_id: The unique identifier for the Hosted Zone

        :type type: str
        :param type: The type of resource record set to begin the record
                     listing from.  Valid choices are:

                     * A
                     * AAAA
                     * CNAME
                     * MX
                     * NS
                     * PTR
                     * SOA
                     * SPF
                     * SRV
                     * TXT

        :type name: str
        :param name: The first name in the lexicographic ordering of domain
                     names to be retrieved

        :type maxitems: int
        :param maxitems: The maximum number of records

        """
        params = {'type': type, 'name': name, 'maxitems': maxitems}
        uri = '/%s/hostedzone/%s/rrset' % (self.Version, hosted_zone_id)
        response = self.make_request('GET', uri, params=params)
        body = response.read()
        boto.log.debug(body)
        if response.status >= 300:
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        return body

    def change_rrsets(self, hosted_zone_id, xml_body):
        """
        Create or change the authoritative DNS information for this
        Hosted Zone.
        Returns a Python data structure with information about the set of
        changes, including the Change ID.

        :type hosted_zone_id: str
        :param hosted_zone_id: The unique identifier for the Hosted Zone

        :type xml_body: str
        :param xml_body: The list of changes to be made, defined in the
                         XML schema defined by the Route53 service.

        """
        uri = '/%s/hostedzone/%s/rrset' % (self.Version, hosted_zone_id)
        response = self.make_request('POST', uri,
                                     {'Content-Type' : 'text/xml'},
                                     xml_body)
        body = response.read()
        boto.log.debug(body)
        if response.status >= 300:
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        e = boto.jsonresponse.Element()
        h = boto.jsonresponse.XmlHandler(e, None)
        h.parse(body)
        return e

    def get_change(self, change_id):
        """
        Get information about a proposed set of changes, as submitted
        by the change_rrsets method.
        Returns a Python data structure with status information about the
        changes.

        :type change_id: str
        :param change_id: The unique identifier for the set of changes.
                          This ID is returned in the response to the
                          change_rrsets method.

        """
        uri = '/%s/change/%s' % (self.Version, change_id)
        response = self.make_request('GET', uri)
        body = response.read()
        boto.log.debug(body)
        if response.status >= 300:
            raise exception.DNSServerError(response.status,
                                           response.reason,
                                           body)
        e = boto.jsonresponse.Element()
        h = boto.jsonresponse.XmlHandler(e, None)
        h.parse(body)
        return e
