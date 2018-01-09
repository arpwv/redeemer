from urllib.request import urlopen

def get_deplorables(url):
  return set(urlopen(url).read().decode('utf8').strip().split("\n"))
