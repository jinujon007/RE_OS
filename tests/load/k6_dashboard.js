// RE_OS — k6 Load Test (T-752)
// 10 VUs × 60s; p95 <500ms; 0 errors
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');

export const options = {
  vus: 10,
  duration: '60s',
  thresholds: {
    http_req_duration: ['p(95)<500'],
    errors: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8050';
const API_KEY = __ENV.DASHBOARD_API_KEY || '';

const params = {
  headers: {
    'X-API-Key': API_KEY,
  },
  timeout: '10s',
};

const endpoints = [
  { url: '/api/health', method: 'GET' },
  { url: '/api/health/live', method: 'GET' },
  { url: '/api/status', method: 'GET' },
  { url: '/api/agents', method: 'GET' },
  { url: '/api/db/state', method: 'GET' },
  { url: '/api/intel/cards', method: 'GET' },
];

export default function () {
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];
  
  const resp = http.get(`${BASE_URL}${ep.url}`, params);
  
  check(resp, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });
  
  errorRate.add(resp.status !== 200);
  
  sleep(1);
}
