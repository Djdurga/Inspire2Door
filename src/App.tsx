import { useCallback, useEffect, useState, type FormEvent } from 'react'
import './App.css'

type Item = {
  id: string
  name: string
  category: string
  price: number
  merchant: string
  neighborhood: string
  eta_minutes: number | null
  stock_count: number
  image_url: string
  tags: string[]
  source?: 'simulation' | 'merchant_csv'
  inventory_updated_at?: string
}

type DispatchResult = {
  order_id: string
  rider: string
  item_count: number
  eta_minutes: number
  distance_km: number
  baseline: string
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const MAPS_SEARCH_URL = 'https://www.google.com/maps/search/?api=1&query=stores+AECS+Layout+Brookefield+Bengaluru'
const categories = ['All finds', 'Clothing', 'Accessories', 'Home', 'Plants', 'Food', 'Beauty', 'Books', 'Gifts']

function App() {
  const [items, setItems] = useState<Item[]>([])
  const [activeCategory, setActiveCategory] = useState('All finds')
  const [ranker, setRanker] = useState<'diverse' | 'popular'>('diverse')
  const [query, setQuery] = useState('')
  const [saved, setSaved] = useState<string[]>([])
  const [bag, setBag] = useState<Item[]>([])
  const [dispatch, setDispatch] = useState<DispatchResult | null>(null)
  const [uploadName, setUploadName] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [importToken, setImportToken] = useState('')
  const [isImporting, setIsImporting] = useState(false)

  const loadItems = useCallback(async (search: string, category: string, feedRanker: 'diverse' | 'popular') => {
    setIsLoading(true)
    const params = new URLSearchParams()
    if (search) params.set('q', search)
    if (category !== 'All finds') params.set('category', category)
    params.set('ranker', feedRanker)
    try {
      const response = await fetch(`${API_URL}/api/items?${params}`)
      if (!response.ok) throw new Error('Catalog request failed')
      setItems(await response.json() as Item[])
      setNotice('')
    } catch {
      setNotice('The local API is offline. Start the project with docker compose up.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadItems('', 'All finds', 'diverse')
  }, [loadItems])

  function chooseCategory(category: string) {
    setActiveCategory(category)
    void loadItems(query, category, ranker)
  }

  function chooseRanker(nextRanker: 'diverse' | 'popular') {
    setRanker(nextRanker)
    void loadItems(query, activeCategory, nextRanker)
  }

  async function searchItems(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void loadItems(query, activeCategory, ranker)
  }

  async function findFromImage(file?: File) {
    if (!file) return
    setUploadName(file.name)
    setQuery(file.name.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' '))
    try {
      const response = await fetch(`${API_URL}/api/visual-search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name }),
      })
      if (!response.ok) throw new Error('Image match request failed')
      setItems(await response.json() as Item[])
      setNotice('Simulation: image matches are inferred from the filename and item tags, not image embeddings.')
    } catch {
      setNotice('Could not reach the simulated visual search service.')
    }
  }

  async function importMerchantCsv(file?: File) {
    if (!file) return
    if (file.size > 2_000_000) {
      setNotice('CSV is too large. The limit is 2 MB.')
      return
    }
    if (!importToken) {
      setNotice('Enter the local merchant import token before importing a CSV.')
      return
    }
    setIsImporting(true)
    try {
      const response = await fetch(`${API_URL}/api/merchant-catalog/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'text/csv', 'X-Merchant-Import-Token': importToken },
        body: await file.text(),
      })
      const result = await response.json() as { detail?: string; upserted?: number }
      if (!response.ok) throw new Error(result.detail ?? 'CSV import failed')
      setNotice(`Imported ${result.upserted} merchant rows. Stock is shown as supplied by that merchant feed; delivery ETA is not available.`)
      void loadItems(query, activeCategory, ranker)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not import merchant CSV.')
    } finally {
      setIsImporting(false)
    }
  }

  async function checkout() {
    if (bag.length === 0) return
    try {
      const response = await fetch(`${API_URL}/api/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_ids: bag.map((item) => item.id) }),
      })
      if (!response.ok) throw new Error('Checkout request failed')
      setDispatch(await response.json() as DispatchResult)
      setBag([])
      void loadItems(query, activeCategory, ranker)
    } catch {
      setNotice('Could not reach the simulated dispatch service.')
    }
  }

  const bagTotal = bag.reduce((total, item) => total + item.price, 0)

  return (
    <div className="app-shell">
      <div className="simulation-bar"><span className="pulse-dot" /> SYNTHETIC CITY SIMULATION<span className="simulation-detail">No real merchants, riders, or orders</span></div>
      <header className="topbar">
        <a className="wordmark" href="#home" aria-label="Inspire2Door home">inspire<span>2</span>door<span className="wordmark-period">.</span></a>
        <nav className="main-nav" aria-label="Main navigation"><a className="nav-active" href="#discover">Discover</a><a href="#nearby">Nearby</a><a href="#about">How it works</a></nav>
        <div className="topbar-actions"><a className="location-label" href={MAPS_SEARCH_URL} target="_blank" rel="noreferrer"><span className="location-mark">⌖</span> AECS Layout, BLR ↗</a><button className="bag-button" onClick={() => document.getElementById('bag')?.scrollIntoView({ behavior: 'smooth' })}>Bag <span>{bag.length}</span></button></div>
      </header>

      <main id="home">
        <section className="intro-section" id="discover">
          <div className="intro-copy">
            <p className="eyebrow"><span>01</span> GOOD FINDS, AROUND THE CORNER</p>
            <h1>See it.<br /><em>Find it</em> nearby.</h1>
            <p className="intro-description">A little inspiration goes a long way. Explore synthetic finds and merchant-submitted stock around AECS Layout and Brookefield.</p>
            <form className="search-form" onSubmit={searchItems}><span className="search-mark" aria-hidden="true">⌕</span><input aria-label="Search nearby finds" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Try ‘linen green’" /><button type="submit">Find it</button></form>
            <label className="image-search"><span className="image-search-icon" aria-hidden="true">↗</span><span>Have a photo? <strong>Find something like it</strong></span><input type="file" accept="image/*" onChange={(event) => void findFromImage(event.target.files?.[0])} /></label>
            <div className="merchant-tools">
              <a className="maps-link" href={MAPS_SEARCH_URL} target="_blank" rel="noreferrer">⌖ Browse public store listings</a>
              <a className="csv-template-link" href="/merchant-inventory-template.csv" download>CSV template</a>
              <label className="import-token-label">Local import token<input type="password" autoComplete="current-password" value={importToken} onChange={(event) => setImportToken(event.target.value)} placeholder="Set in local environment" /></label>
              <label className={`import-csv-button ${isImporting ? 'is-busy' : ''}`}>{isImporting ? 'Importing...' : 'Import authorized inventory CSV'}<input type="file" accept=".csv,text/csv" disabled={isImporting} onChange={(event) => { void importMerchantCsv(event.target.files?.[0]); event.currentTarget.value = '' }} /></label>
              <span className="merchant-data-note">Listings are not live inventory. Imported stock reflects the merchant CSV timestamp.</span>
            </div>
            {uploadName && <p className="upload-name">Selected: {uploadName}</p>}
          </div>
          <div className="hero-art" aria-label="Local style inspiration">
            <img className="hero-photo" src="https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1100&q=85" alt="Friends browsing a clothing boutique" />
            <div className="hero-sticker"><span>MADE<br />AROUND<br />HERE</span><b>✳</b></div>
            <div className="hero-caption"><span>THE INDIE EDIT</span><span>BLR / VOL. 01</span></div>
            <div className="floating-note"><span className="note-dot" /> AECS Layout<br />synthetic city model</div>
          </div>
        </section>

        <section className="discovery-section" id="nearby">
          <div className="section-heading"><div><p className="eyebrow"><span>02</span> YOUR NEIGHBORHOOD, EDITED</p><h2>Today’s <em>good finds</em></h2></div><p className="result-note">Curated from nearby independent shops <span>↘</span></p></div>
          <div className="category-row" role="group" aria-label="Filter by category">
            {categories.map((category, index) => <button key={category} className={`category-button ${activeCategory === category ? 'selected' : ''}`} onClick={() => chooseCategory(category)}><span className="category-number">0{index + 1}</span>{category}</button>)}
            <span className="category-count">{items.length} SYNTHETIC FINDS</span>
          </div>
          <div className="ranking-row">
            <span className="ranking-label">RANKING VIEW</span>
            <div className="ranking-toggle" role="group" aria-label="Feed ranking">
              <button aria-pressed={ranker === 'diverse'} onClick={() => chooseRanker('diverse')}>Diverse feed</button>
              <button aria-pressed={ranker === 'popular'} onClick={() => chooseRanker('popular')}>Popularity baseline</button>
            </div>
            <span className="ranking-caption">SIMULATED SIGNALS ONLY</span>
          </div>
          {notice && <p className="notice" role="status">{notice}</p>}
          {isLoading ? <div className="loading-state">Finding the good stuff...</div> : (
            <div className="product-grid">
              {items.map((item, index) => <article className={`product-card card-${index % 4}`} key={item.id}>
                <div className="product-image-wrap">{item.image_url && <img src={item.image_url} alt={item.name} loading="lazy" />}<span className="arrival-pill">{item.source === 'merchant_csv' ? 'ETA unavailable' : `SIM ETA ${item.eta_minutes} min`}</span><span className="stock-pill">{item.stock_count} {item.source === 'merchant_csv' ? 'listed' : 'simulated'} in stock</span><button className={`save-button ${saved.includes(item.id) ? 'is-saved' : ''}`} aria-label={saved.includes(item.id) ? `Unsave ${item.name}` : `Save ${item.name}`} onClick={() => setSaved((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])}>{saved.includes(item.id) ? '♥' : '♡'}</button>{item.source === 'merchant_csv' ? <a className="quick-add store-directions" href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${item.merchant} ${item.neighborhood}`)}`} target="_blank" rel="noreferrer">Find store</a> : <button className="quick-add" onClick={() => setBag((current) => [...current, item])}>+ Add</button>}</div>
                <div className="product-info"><div className="product-title-row"><h3>{item.name}</h3><span>₹{item.price.toLocaleString('en-IN')}</span></div><p>{item.merchant} <span>·</span> {item.neighborhood}</p>{item.source === 'merchant_csv' && item.inventory_updated_at && <p className="inventory-timestamp">Merchant feed updated {new Date(item.inventory_updated_at).toLocaleString()}</p>}</div>
              </article>)}
              {items.length === 0 && <p className="empty-state">No nearby finds match that just yet. Try another search.</p>}
            </div>
          )}
        </section>

        <section className="dispatch-band" id="about">
          <div className="dispatch-copy"><p className="eyebrow"><span>03</span> SYNTHETIC LAST MILE</p><h2>Good things<br />are <em>closer</em> than you think.</h2><p>Dispatch and ETA apply only to synthetic demo items. Merchant-imported inventory has no delivery promise.</p></div>
          <div className="city-panel"><div className="city-panel-header"><span>AECS LAYOUT / SIMULATION</span><span className="live-indicator">● SIM</span></div><div className="city-grid"><span className="city-road road-a" /><span className="city-road road-b" /><span className="city-road road-c" /><span className="city-block block-a">AECS MAIN RD</span><span className="city-block block-b">ITPL MAIN RD</span><span className="city-block block-c">KUNDALAHALLI</span><span className="map-pin pin-shop">S</span><span className="map-pin pin-rider">R</span><span className="map-pin pin-home">⌂</span><span className="route-line" /></div><div className="city-panel-footer"><span><i className="legend-shop" /> SHOP</span><span><i className="legend-rider" /> RIDER</span><span>3 SYNTHETIC RIDERS</span></div></div>
        </section>

        <section className="bag-section" id="bag">
          <div><p className="eyebrow"><span>04</span> YOUR LITTLE LOCAL HAUL</p><h2>In the <em>bag</em> <span className="bag-total-count">{bag.length}</span></h2></div>
          {bag.length === 0 ? <p className="bag-empty">Your bag is taking a neighborhood stroll. Add a find to bring it back.</p> : <div className="bag-checkout"><div>{bag.map((item, index) => <p key={`${item.id}-${index}`}>{item.name}<span>₹{item.price.toLocaleString('en-IN')}</span></p>)}</div><button onClick={() => void checkout()}>Simulate dispatch · ₹{bagTotal.toLocaleString('en-IN')}</button></div>}
          {dispatch && <div className="dispatch-result" role="status"><strong>Order {dispatch.order_id} is on its way.</strong><span>{dispatch.rider} · {dispatch.item_count} finds · estimated {dispatch.eta_minutes} min · {dispatch.distance_km} km</span><small>Baseline: {dispatch.baseline}. Simulation result, not a real delivery promise.</small></div>}
        </section>
      </main>

      <footer className="footer"><a className="wordmark" href="#home">inspire<span>2</span>door<span className="wordmark-period">.</span></a><p>A portfolio simulation. Synthetic city, synthetic results.</p><a href="/docs/architecture.md">Read the build notes ↗</a></footer>
    </div>
  )
}

export default App
