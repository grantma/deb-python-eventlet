# coding: utf-8
"""Tests for the eventlet.support.greendns module"""

import os
import socket
import tempfile
import time

from eventlet.support import greendns
from eventlet.support.greendns import dns
import tests
import tests.mock


class TestHostsResolver(tests.LimitedTestCase):

    def _make_host_resolver(self):
        """Returns a HostResolver instance

        The hosts file will be empty but accessible as a py.path.local
        instance using the ``hosts`` attribute.
        """
        hosts = tempfile.NamedTemporaryFile()
        hr = greendns.HostsResolver(fname=hosts.name)
        hr.hosts = hosts
        hr._last_stat = 0
        return hr

    def test_default_fname(self):
        hr = greendns.HostsResolver()
        assert os.path.exists(hr.fname)

    def test_readlines_lines(self):
        hr = self._make_host_resolver()
        hr.hosts.write(b'line0\n')
        hr.hosts.flush()
        assert hr._readlines() == ['line0']
        hr._last_stat = 0
        hr.hosts.write(b'line1\n')
        hr.hosts.flush()
        assert hr._readlines() == ['line0', 'line1']
        hr._last_stat = 0
        hr.hosts.write(b'#comment0\nline0\n #comment1\nline1')
        assert hr._readlines() == ['line0', 'line1']

    def test_readlines_missing_file(self):
        hr = self._make_host_resolver()
        hr.hosts.close()
        hr._last_stat = 0
        assert hr._readlines() == []

    def test_load_no_contents(self):
        hr = self._make_host_resolver()
        hr._load()
        assert not hr._v4
        assert not hr._v6
        assert not hr._aliases

    def test_load_v4_v6_cname_aliases(self):
        hr = self._make_host_resolver()
        hr.hosts.write(b'1.2.3.4 v4.example.com v4\n'
                       b'dead:beef::1 v6.example.com v6\n')
        hr.hosts.flush()
        hr._load()
        assert hr._v4 == {'v4.example.com': '1.2.3.4', 'v4': '1.2.3.4'}
        assert hr._v6 == {'v6.example.com': 'dead:beef::1',
                          'v6': 'dead:beef::1'}
        assert hr._aliases == {'v4': 'v4.example.com',
                               'v6': 'v6.example.com'}

    def test_load_v6_link_local(self):
        hr = self._make_host_resolver()
        hr.hosts.write(b'fe80:: foo\n'
                       b'fe80:dead:beef::1 bar\n')
        hr.hosts.flush()
        hr._load()
        assert not hr._v4
        assert not hr._v6

    def test_query_A(self):
        hr = self._make_host_resolver()
        hr._v4 = {'v4.example.com': '1.2.3.4'}
        ans = hr.query('v4.example.com')
        assert ans[0].address == '1.2.3.4'

    def test_query_ans_types(self):
        # This assumes test_query_A above succeeds
        hr = self._make_host_resolver()
        hr._v4 = {'v4.example.com': '1.2.3.4'}
        hr._last_stat = time.time()
        ans = hr.query('v4.example.com')
        assert isinstance(ans, greendns.dns.resolver.Answer)
        assert ans.response is None
        assert ans.qname == dns.name.from_text('v4.example.com')
        assert ans.rdtype == dns.rdatatype.A
        assert ans.rdclass == dns.rdataclass.IN
        assert ans.canonical_name == dns.name.from_text('v4.example.com')
        assert ans.expiration
        assert isinstance(ans.rrset, dns.rrset.RRset)
        assert ans.rrset.rdtype == dns.rdatatype.A
        assert ans.rrset.rdclass == dns.rdataclass.IN
        ttl = greendns.HOSTS_TTL
        assert ttl - 1 <= ans.rrset.ttl <= ttl + 1
        rr = ans.rrset[0]
        assert isinstance(rr, greendns.dns.rdtypes.IN.A.A)
        assert rr.rdtype == dns.rdatatype.A
        assert rr.rdclass == dns.rdataclass.IN
        assert rr.address == '1.2.3.4'

    def test_query_AAAA(self):
        hr = self._make_host_resolver()
        hr._v6 = {'v6.example.com': 'dead:beef::1'}
        ans = hr.query('v6.example.com', dns.rdatatype.AAAA)
        assert ans[0].address == 'dead:beef::1'

    def test_query_unknown_raises(self):
        hr = self._make_host_resolver()
        with tests.assert_raises(greendns.dns.resolver.NoAnswer):
            hr.query('example.com')

    def test_query_unknown_no_raise(self):
        hr = self._make_host_resolver()
        ans = hr.query('example.com', raise_on_no_answer=False)
        assert isinstance(ans, greendns.dns.resolver.Answer)
        assert ans.response is None
        assert ans.qname == dns.name.from_text('example.com')
        assert ans.rdtype == dns.rdatatype.A
        assert ans.rdclass == dns.rdataclass.IN
        assert ans.canonical_name == dns.name.from_text('example.com')
        assert ans.expiration
        assert isinstance(ans.rrset, greendns.dns.rrset.RRset)
        assert ans.rrset.rdtype == dns.rdatatype.A
        assert ans.rrset.rdclass == dns.rdataclass.IN
        assert len(ans.rrset) == 0

    def test_query_CNAME(self):
        hr = self._make_host_resolver()
        hr._aliases = {'host': 'host.example.com'}
        ans = hr.query('host', dns.rdatatype.CNAME)
        assert ans[0].target == dns.name.from_text('host.example.com')
        assert str(ans[0].target) == 'host.example.com.'

    def test_query_unknown_type(self):
        hr = self._make_host_resolver()
        with tests.assert_raises(greendns.dns.resolver.NoAnswer):
            hr.query('example.com', dns.rdatatype.MX)

    def test_getaliases(self):
        hr = self._make_host_resolver()
        hr._aliases = {'host': 'host.example.com',
                       'localhost': 'host.example.com'}
        res = set(hr.getaliases('host'))
        assert res == set(['host.example.com', 'localhost'])

    def test_getaliases_unknown(self):
        hr = self._make_host_resolver()
        assert hr.getaliases('host.example.com') == []

    def test_getaliases_fqdn(self):
        hr = self._make_host_resolver()
        hr._aliases = {'host': 'host.example.com'}
        res = set(hr.getaliases('host.example.com'))
        assert res == set(['host'])


def _make_mock_base_resolver():
    """A mocked base resolver class"""
    class RR(object):
        pass

    class Resolver(object):
        aliases = ['cname.example.com']
        raises = None
        rr = RR()

        def query(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            if self.raises:
                raise self.raises()
            if hasattr(self, 'rrset'):
                rrset = self.rrset
            else:
                rrset = [self.rr]
            return greendns.HostsAnswer('foo', 1, 1, rrset, False)

        def getaliases(self, *args, **kwargs):
            return self.aliases

    return Resolver


class TestProxyResolver(tests.LimitedTestCase):

    def test_clear(self):
        rp = greendns.ResolverProxy()
        resolver = rp._resolver
        rp.clear()
        assert rp._resolver != resolver

    def _make_mock_hostsresolver(self):
        """A mocked HostsResolver"""
        base_resolver = _make_mock_base_resolver()
        base_resolver.rr.address = '1.2.3.4'
        return base_resolver()

    def _make_mock_resolver(self):
        """A mocked Resolver"""
        base_resolver = _make_mock_base_resolver()
        base_resolver.rr.address = '5.6.7.8'
        return base_resolver()

    def test_hosts(self):
        hostsres = self._make_mock_hostsresolver()
        rp = greendns.ResolverProxy(hostsres)
        ans = rp.query('host.example.com')
        assert ans[0].address == '1.2.3.4'

    def test_hosts_noanswer(self):
        hostsres = self._make_mock_hostsresolver()
        res = self._make_mock_resolver()
        rp = greendns.ResolverProxy(hostsres)
        rp._resolver = res
        hostsres.raises = greendns.dns.resolver.NoAnswer
        ans = rp.query('host.example.com')
        assert ans[0].address == '5.6.7.8'

    def test_resolver(self):
        res = self._make_mock_resolver()
        rp = greendns.ResolverProxy()
        rp._resolver = res
        ans = rp.query('host.example.com')
        assert ans[0].address == '5.6.7.8'

    def test_noanswer(self):
        res = self._make_mock_resolver()
        rp = greendns.ResolverProxy()
        rp._resolver = res
        res.raises = greendns.dns.resolver.NoAnswer
        with tests.assert_raises(greendns.dns.resolver.NoAnswer):
            rp.query('host.example.com')

    def test_nxdomain(self):
        res = self._make_mock_resolver()
        rp = greendns.ResolverProxy()
        rp._resolver = res
        res.raises = greendns.dns.resolver.NXDOMAIN
        with tests.assert_raises(greendns.dns.resolver.NXDOMAIN):
            rp.query('host.example.com')

    def test_noanswer_hosts(self):
        hostsres = self._make_mock_hostsresolver()
        res = self._make_mock_resolver()
        rp = greendns.ResolverProxy(hostsres)
        rp._resolver = res
        hostsres.raises = greendns.dns.resolver.NoAnswer
        res.raises = greendns.dns.resolver.NoAnswer
        with tests.assert_raises(greendns.dns.resolver.NoAnswer):
            rp.query('host.example.com')

    def _make_mock_resolver_aliases(self):

        class RR(object):
            target = 'host.example.com'

        class Resolver(object):
            call_count = 0
            exc_type = greendns.dns.resolver.NoAnswer

            def query(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self.call_count += 1
                if self.call_count < 2:
                    return greendns.HostsAnswer(args[0], 1, 5, [RR()], False)
                else:
                    raise self.exc_type()

        return Resolver()

    def test_getaliases(self):
        aliases_res = self._make_mock_resolver_aliases()
        rp = greendns.ResolverProxy()
        rp._resolver = aliases_res
        aliases = set(rp.getaliases('alias.example.com'))
        assert aliases == set(['host.example.com'])

    def test_getaliases_fqdn(self):
        aliases_res = self._make_mock_resolver_aliases()
        rp = greendns.ResolverProxy()
        rp._resolver = aliases_res
        rp._resolver.call_count = 1
        assert rp.getaliases('host.example.com') == []

    def test_getaliases_nxdomain(self):
        aliases_res = self._make_mock_resolver_aliases()
        rp = greendns.ResolverProxy()
        rp._resolver = aliases_res
        rp._resolver.call_count = 1
        rp._resolver.exc_type = greendns.dns.resolver.NXDOMAIN
        assert rp.getaliases('host.example.com') == []


class TestResolve(tests.LimitedTestCase):

    def setUp(self):
        base_resolver = _make_mock_base_resolver()
        base_resolver.rr.address = '1.2.3.4'
        self._old_resolver = greendns.resolver
        greendns.resolver = base_resolver()

    def tearDown(self):
        greendns.resolver = self._old_resolver

    def test_A(self):
        ans = greendns.resolve('host.example.com', socket.AF_INET)
        assert ans[0].address == '1.2.3.4'
        assert greendns.resolver.args == ('host.example.com', dns.rdatatype.A)

    def test_AAAA(self):
        greendns.resolver.rr.address = 'dead:beef::1'
        ans = greendns.resolve('host.example.com', socket.AF_INET6)
        assert ans[0].address == 'dead:beef::1'
        assert greendns.resolver.args == ('host.example.com', dns.rdatatype.AAAA)

    def test_unknown_rdtype(self):
        with tests.assert_raises(socket.gaierror):
            greendns.resolve('host.example.com', socket.AF_INET6 + 1)

    def test_timeout(self):
        greendns.resolver.raises = greendns.dns.exception.Timeout
        with tests.assert_raises(socket.gaierror):
            greendns.resolve('host.example.com')

    def test_exc(self):
        greendns.resolver.raises = greendns.dns.exception.DNSException
        with tests.assert_raises(socket.gaierror):
            greendns.resolve('host.example.com')

    def test_noraise_noanswer(self):
        greendns.resolver.rrset = None
        ans = greendns.resolve('example.com', raises=False)
        assert not ans.rrset

    def test_noraise_nxdomain(self):
        greendns.resolver.raises = greendns.dns.resolver.NXDOMAIN
        ans = greendns.resolve('example.com', raises=False)
        assert not ans.rrset


class TestResolveCname(tests.LimitedTestCase):

    def setUp(self):
        base_resolver = _make_mock_base_resolver()
        base_resolver.rr.target = 'cname.example.com'
        self._old_resolver = greendns.resolver
        greendns.resolver = base_resolver()

    def tearDown(self):
        greendns.resolver = self._old_resolver

    def test_success(self):
        cname = greendns.resolve_cname('alias.example.com')
        assert cname == 'cname.example.com'

    def test_timeout(self):
        greendns.resolver.raises = greendns.dns.exception.Timeout
        with tests.assert_raises(socket.gaierror):
            greendns.resolve_cname('alias.example.com')

    def test_nodata(self):
        greendns.resolver.raises = greendns.dns.exception.DNSException
        with tests.assert_raises(socket.gaierror):
            greendns.resolve_cname('alias.example.com')

    def test_no_answer(self):
        greendns.resolver.raises = greendns.dns.resolver.NoAnswer
        assert greendns.resolve_cname('host.example.com') == 'host.example.com'


def _make_mock_resolve():
    """A stubbed out resolve function

    This monkeypatches the greendns.resolve() function with a mock.
    You must give it answers by calling .add().
    """

    class MockAnswer(list):
        pass

    class MockResolve(object):

        def __init__(self):
            self.answers = {}

        def __call__(self, name, family=socket.AF_INET, raises=True):
            qname = dns.name.from_text(name)
            try:
                rrset = self.answers[name][family]
            except KeyError:
                if raises:
                    raise greendns.dns.resolver.NoAnswer()
                rrset = dns.rrset.RRset(qname, 1, 1)
            ans = MockAnswer()
            ans.qname = qname
            ans.rrset = rrset
            ans.extend(rrset.items)
            return ans

        def add(self, name, addr):
            """Add an address to a name and family"""
            try:
                rdata = dns.rdtypes.IN.A.A(dns.rdataclass.IN,
                                           dns.rdatatype.A, addr)
                family = socket.AF_INET
            except (socket.error, dns.exception.SyntaxError):
                rdata = dns.rdtypes.IN.AAAA.AAAA(dns.rdataclass.IN,
                                                 dns.rdatatype.AAAA, addr)
                family = socket.AF_INET6
            family_dict = self.answers.setdefault(name, {})
            rrset = family_dict.get(family)
            if not rrset:
                family_dict[family] = rrset = dns.rrset.RRset(
                    dns.name.from_text(name), rdata.rdclass, rdata.rdtype)
            rrset.add(rdata)

    resolve = MockResolve()
    return resolve


class TestGetaddrinfo(tests.LimitedTestCase):

    def _make_mock_resolve_cname(self):
        """A stubbed out cname function"""

        class ResolveCname(object):
            qname = None
            cname = 'cname.example.com'

            def __call__(self, host):
                self.qname = host
                return self.cname

        resolve_cname = ResolveCname()
        return resolve_cname

    def setUp(self):
        self._old_resolve = greendns.resolve
        self._old_resolve_cname = greendns.resolve_cname
        self._old_orig_getaddrinfo = greendns.socket.getaddrinfo

    def tearDown(self):
        greendns.resolve = self._old_resolve
        greendns.resolve_cname = self._old_resolve_cname
        greendns.socket.getaddrinfo = self._old_orig_getaddrinfo

    def test_getaddrinfo(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '127.0.0.2')
        greendns.resolve.add('example.com', '::1')
        res = greendns.getaddrinfo('example.com', 'domain')
        addr = ('127.0.0.2', 53)
        tcp = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, addr)
        udp = (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, addr)
        addr = ('::1', 53, 0, 0)
        tcp6 = (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, addr)
        udp6 = (socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, addr)
        filt_res = [ai[:3] + (ai[4],) for ai in res]
        assert tcp in filt_res
        assert udp in filt_res
        assert tcp6 in filt_res
        assert udp6 in filt_res

    def test_getaddrinfo_idn(self):
        greendns.resolve = _make_mock_resolve()
        idn_name = u'евентлет.com'
        greendns.resolve.add(idn_name.encode('idna').decode('ascii'), '127.0.0.2')
        res = greendns.getaddrinfo(idn_name, 'domain')
        addr = ('127.0.0.2', 53)
        tcp = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, addr)
        udp = (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, addr)
        filt_res = [ai[:3] + (ai[4],) for ai in res]
        assert tcp in filt_res
        assert udp in filt_res

    def test_getaddrinfo_inet(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '127.0.0.2')
        res = greendns.getaddrinfo('example.com', 'domain', socket.AF_INET)
        addr = ('127.0.0.2', 53)
        tcp = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, addr)
        udp = (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, addr)
        assert tcp in [ai[:3] + (ai[4],) for ai in res]
        assert udp in [ai[:3] + (ai[4],) for ai in res]

    def test_getaddrinfo_inet6(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '::1')
        res = greendns.getaddrinfo('example.com', 'domain', socket.AF_INET6)
        addr = ('::1', 53, 0, 0)
        tcp = (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, addr)
        udp = (socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, addr)
        assert tcp in [ai[:3] + (ai[4],) for ai in res]
        assert udp in [ai[:3] + (ai[4],) for ai in res]

    def test_getaddrinfo_only_a_ans(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '1.2.3.4')
        res = greendns.getaddrinfo('example.com', 0)
        addr = [('1.2.3.4', 0)] * len(res)
        assert addr == [ai[-1] for ai in res]

    def test_getaddrinfo_only_aaaa_ans(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', 'dead:beef::1')
        res = greendns.getaddrinfo('example.com', 0)
        addr = [('dead:beef::1', 0, 0, 0)] * len(res)
        assert addr == [ai[-1] for ai in res]

    def test_getaddrinfo_hosts_only_ans_with_timeout(self):
        def clear_raises(res_self):
            res_self.raises = None
            return greendns.dns.resolver.NoAnswer()

        hostsres = _make_mock_base_resolver()
        hostsres.raises = clear_raises
        hostsres.rr.address = '1.2.3.4'
        greendns.resolver = greendns.ResolverProxy(hostsres())
        res = _make_mock_base_resolver()
        res.raises = greendns.dns.exception.Timeout
        greendns.resolver._resolver = res()

        result = greendns.getaddrinfo('example.com', 0, 0)
        addr = [('1.2.3.4', 0)] * len(result)
        assert addr == [ai[-1] for ai in result]

    def test_getaddrinfo_hosts_only_ans_with_error(self):
        def clear_raises(res_self):
            res_self.raises = None
            return greendns.dns.resolver.NoAnswer()

        hostsres = _make_mock_base_resolver()
        hostsres.raises = clear_raises
        hostsres.rr.address = '1.2.3.4'
        greendns.resolver = greendns.ResolverProxy(hostsres())
        res = _make_mock_base_resolver()
        res.raises = greendns.dns.exception.DNSException
        greendns.resolver._resolver = res()

        result = greendns.getaddrinfo('example.com', 0, 0)
        addr = [('1.2.3.4', 0)] * len(result)
        assert addr == [ai[-1] for ai in result]

    def test_getaddrinfo_hosts_only_timeout(self):
        hostsres = _make_mock_base_resolver()
        hostsres.raises = greendns.dns.resolver.NoAnswer
        greendns.resolver = greendns.ResolverProxy(hostsres())
        res = _make_mock_base_resolver()
        res.raises = greendns.dns.exception.Timeout
        greendns.resolver._resolver = res()

        with tests.assert_raises(socket.gaierror):
            greendns.getaddrinfo('example.com', 0, 0)

    def test_getaddrinfo_hosts_only_dns_error(self):
        hostsres = _make_mock_base_resolver()
        hostsres.raises = greendns.dns.resolver.NoAnswer
        greendns.resolver = greendns.ResolverProxy(hostsres())
        res = _make_mock_base_resolver()
        res.raises = greendns.dns.exception.DNSException
        greendns.resolver._resolver = res()

        with tests.assert_raises(socket.gaierror):
            greendns.getaddrinfo('example.com', 0, 0)

    def test_canonname(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('host.example.com', '1.2.3.4')
        greendns.resolve_cname = self._make_mock_resolve_cname()
        res = greendns.getaddrinfo('host.example.com', 0,
                                   0, 0, 0, socket.AI_CANONNAME)
        assert res[0][3] == 'cname.example.com'

    def test_host_none(self):
        res = greendns.getaddrinfo(None, 80)
        for addr in set(ai[-1] for ai in res):
            assert addr in [('127.0.0.1', 80), ('::1', 80, 0, 0)]

    def test_host_none_passive(self):
        res = greendns.getaddrinfo(None, 80, 0, 0, 0, socket.AI_PASSIVE)
        for addr in set(ai[-1] for ai in res):
            assert addr in [('0.0.0.0', 80), ('::', 80, 0, 0)]

    def test_v4mapped(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '1.2.3.4')
        res = greendns.getaddrinfo('example.com', 80,
                                   socket.AF_INET6, 0, 0, socket.AI_V4MAPPED)
        addrs = set(ai[-1] for ai in res)
        assert addrs == set([('::ffff:1.2.3.4', 80, 0, 0)])

    def test_v4mapped_all(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '1.2.3.4')
        greendns.resolve.add('example.com', 'dead:beef::1')
        res = greendns.getaddrinfo('example.com', 80, socket.AF_INET6, 0, 0,
                                   socket.AI_V4MAPPED | socket.AI_ALL)
        addrs = set(ai[-1] for ai in res)
        for addr in addrs:
            assert addr in [('::ffff:1.2.3.4', 80, 0, 0),
                            ('dead:beef::1', 80, 0, 0)]

    def test_numericserv(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '1.2.3.4')
        with tests.assert_raises(socket.gaierror):
            greendns.getaddrinfo('example.com', 'www', 0, 0, 0, socket.AI_NUMERICSERV)

    def test_numerichost(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '1.2.3.4')
        with tests.assert_raises(socket.gaierror):
            greendns.getaddrinfo('example.com', 80, 0, 0, 0, socket.AI_NUMERICHOST)

    def test_noport(self):
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('example.com', '1.2.3.4')
        ai = greendns.getaddrinfo('example.com', None)
        assert ai[0][-1][1] == 0

    def test_AI_ADDRCONFIG(self):
        # When the users sets AI_ADDRCONFIG but only has an IPv4
        # address configured we will iterate over the results, but the
        # call for the IPv6 address will fail rather then return an
        # empty list.  In that case we should catch the exception and
        # only return the ones which worked.
        def getaddrinfo(addr, port, family, socktype, proto, aiflags):
            if addr == '127.0.0.1':
                return [(socket.AF_INET, 1, 0, '', ('127.0.0.1', 0))]
            elif addr == '::1' and aiflags & socket.AI_ADDRCONFIG:
                raise socket.error(socket.EAI_ADDRFAMILY,
                                   'Address family for hostname not supported')
            elif addr == '::1' and not aiflags & socket.AI_ADDRCONFIG:
                return [(socket.AF_INET6, 1, 0, '', ('::1', 0, 0, 0))]
        greendns.socket.getaddrinfo = getaddrinfo
        greendns.resolve = _make_mock_resolve()
        greendns.resolve.add('localhost', '127.0.0.1')
        greendns.resolve.add('localhost', '::1')
        res = greendns.getaddrinfo('localhost', None,
                                   0, 0, 0, socket.AI_ADDRCONFIG)
        assert res == [(socket.AF_INET, 1, 0, '', ('127.0.0.1', 0))]

    def test_AI_ADDRCONFIG_noaddr(self):
        # If AI_ADDRCONFIG is used but there is no address we need to
        # get an exception, not an empty list.
        def getaddrinfo(addr, port, family, socktype, proto, aiflags):
            raise socket.error(socket.EAI_ADDRFAMILY,
                               'Address family for hostname not supported')
        greendns.socket.getaddrinfo = getaddrinfo
        greendns.resolve = _make_mock_resolve()
        try:
            greendns.getaddrinfo('::1', None, 0, 0, 0, socket.AI_ADDRCONFIG)
        except socket.error as e:
            assert e.errno == socket.EAI_ADDRFAMILY


class TestIsIpAddr(tests.LimitedTestCase):

    def test_isv4(self):
        assert greendns.is_ipv4_addr('1.2.3.4')

    def test_isv4_false(self):
        assert not greendns.is_ipv4_addr('260.0.0.0')

    def test_isv6(self):
        assert greendns.is_ipv6_addr('dead:beef::1')

    def test_isv6_invalid(self):
        assert not greendns.is_ipv6_addr('foobar::1')

    def test_v4(self):
        assert greendns.is_ip_addr('1.2.3.4')

    def test_v4_illegal(self):
        assert not greendns.is_ip_addr('300.0.0.1')

    def test_v6_addr(self):
        assert greendns.is_ip_addr('::1')

    def test_isv4_none(self):
        assert not greendns.is_ipv4_addr(None)

    def test_isv6_none(self):
        assert not greendns.is_ipv6_addr(None)

    def test_none(self):
        assert not greendns.is_ip_addr(None)


class TestGethostbyname(tests.LimitedTestCase):

    def setUp(self):
        self._old_resolve = greendns.resolve
        greendns.resolve = _make_mock_resolve()

    def tearDown(self):
        greendns.resolve = self._old_resolve

    def test_ipaddr(self):
        assert greendns.gethostbyname('1.2.3.4') == '1.2.3.4'

    def test_name(self):
        greendns.resolve.add('host.example.com', '1.2.3.4')
        assert greendns.gethostbyname('host.example.com') == '1.2.3.4'


class TestGetaliases(tests.LimitedTestCase):

    def _make_mock_resolver(self):
        base_resolver = _make_mock_base_resolver()
        resolver = base_resolver()
        resolver.aliases = ['cname.example.com']
        return resolver

    def setUp(self):
        self._old_resolver = greendns.resolver
        greendns.resolver = self._make_mock_resolver()

    def tearDown(self):
        greendns.resolver = self._old_resolver

    def test_getaliases(self):
        assert greendns.getaliases('host.example.com') == ['cname.example.com']


class TestGethostbyname_ex(tests.LimitedTestCase):

    def _make_mock_getaliases(self):

        class GetAliases(object):
            aliases = ['cname.example.com']

            def __call__(self, *args, **kwargs):
                return self.aliases

        getaliases = GetAliases()
        return getaliases

    def setUp(self):
        self._old_resolve = greendns.resolve
        greendns.resolve = _make_mock_resolve()
        self._old_getaliases = greendns.getaliases

    def tearDown(self):
        greendns.resolve = self._old_resolve
        greendns.getaliases = self._old_getaliases

    def test_ipaddr(self):
        res = greendns.gethostbyname_ex('1.2.3.4')
        assert res == ('1.2.3.4', [], ['1.2.3.4'])

    def test_name(self):
        greendns.resolve.add('host.example.com', '1.2.3.4')
        greendns.getaliases = self._make_mock_getaliases()
        greendns.getaliases.aliases = []
        res = greendns.gethostbyname_ex('host.example.com')
        assert res == ('host.example.com', [], ['1.2.3.4'])

    def test_multiple_addrs(self):
        greendns.resolve.add('host.example.com', '1.2.3.4')
        greendns.resolve.add('host.example.com', '1.2.3.5')
        greendns.getaliases = self._make_mock_getaliases()
        greendns.getaliases.aliases = []
        res = greendns.gethostbyname_ex('host.example.com')
        assert res == ('host.example.com', [], ['1.2.3.4', '1.2.3.5'])


def test_reverse_name():
    tests.run_isolated('greendns_from_address_203.py')


def test_proxy_resolve_unqualified():
    # https://github.com/eventlet/eventlet/issues/363
    rp = greendns.ResolverProxy(filename=None)
    rp._resolver.search.append(dns.name.from_text('example.com'))
    with tests.mock.patch('dns.resolver.Resolver.query', side_effect=dns.resolver.NoAnswer) as m:
        try:
            rp.query('machine')
            assert False, 'Expected NoAnswer exception'
        except dns.resolver.NoAnswer:
            pass
        assert any(call[0][0] == dns.name.from_text('machine') for call in m.call_args_list)
        assert any(call[0][0] == dns.name.from_text('machine.') for call in m.call_args_list)
