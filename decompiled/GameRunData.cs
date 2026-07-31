using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

public class GameRunData
{
	public string OriginalVersion;

	public string Version;

	public int MapGenSeed;

	public string ConfigName;

	public string SelectedName;

	public eGameDifficulties GameDifficulty;

	public int PlayerAmount;

	public int CurrentLifePool;

	public List<eExpansions> Expansions;

	[JsonIgnore]
	public Dictionary<string, (ePlatformIds Platform, string PlatformId)> CharacterNomenclatorMap;

	[JsonIgnore]
	public List<List<(Entity, bool IsMegaHexPath)>> DebugRoadData;

	[JsonInclude]
	[JsonPropertyName("Entities")]
	private List<Entity> _entities;

	public List<QuestData> FutureQuests;

	public List<QuestState> ActiveQuests;

	public List<QuestState> CompletedQuests;

	public List<QuestState> FailedQuests;

	public List<string> Achievements;

	public string NPCHostID;

	public AdventureState AdventureState;

	public VenueState VenueState;

	public DungeonState DungeonState;

	[JsonIgnore]
	public CombatState CombatState;

	public Dictionary<string, FollowerState> PlayerFollowers;

	public Dictionary<eSkills, int> SkillCoolDown;

	public Dictionary<string, int> Stats;

	public Dictionary<string, int> ItemPools;

	public List<string> AnonymousEvents;

	public Dictionary<eGameDifficultyHandles, int> HouseRules;

	public ShuffleBag<bool> SmartLootShuffle;

	public string MultiplayerFirstLootPlayerGuid;

	public Dictionary<string, ParseTextResult> QuestViewDataCache;

	public ePhases? Phase;

	public JsonElement? PhaseData;

	[Obsolete("Use AdventureState.MapState.GameStageIndex")]
	public int GameStageIndex;

	[Obsolete("Use AdventureState.MapState.GameStageRoundStart")]
	public int GameStageRoundStart;

	[Obsolete("Use AdventureState.MapState.ActiveScourges")]
	public List<eScourges> ActiveScourges;

	[Obsolete("Use AdventureState.MapState.ChaosState")]
	public ChaosState ChaosState;

	[Obsolete("Use AdventureState.MapState.RoundCount")]
	public int RoundCount;

	[Obsolete("Use AdventureState.MapState.WorldModifiers")]
	public Dictionary<eWorldModifiers, int> WorldModifiers;

	[JsonIgnore]
	public List<Entity> Entities => _entities;

	public static GameRunData Create(string pGameVersion, string pAdventureConfig, List<eExpansions> pExpansions = null, eGameDifficulties pGameDifficulty = eGameDifficulties.APPRENTICE, Dictionary<eGameDifficultyHandles, int> pHouseRules = null)
	{
		if (!Env.Configs.Adventures.TryGetValue(pAdventureConfig, out var _))
		{
			throw new Exception("You must provide a valid Adventure Config Name! -> " + pAdventureConfig);
		}
		GameRunData result = new GameRunData
		{
			HouseRules = ((pHouseRules != null && pHouseRules.Count > 0) ? pHouseRules : null),
			ConfigName = pAdventureConfig,
			ItemPools = new Dictionary<string, int> { ["CURRENCY_LORE"] = 0 },
			FutureQuests = new List<QuestData>(),
			ActiveQuests = new List<QuestState>(),
			CompletedQuests = new List<QuestState>(),
			FailedQuests = new List<QuestState>(),
			Achievements = new List<string>(),
			Stats = new Dictionary<string, int>(),
			_entities = new List<Entity>(),
			SkillCoolDown = new Dictionary<eSkills, int>(),
			PlayerFollowers = new Dictionary<string, FollowerState>(),
			QuestViewDataCache = new Dictionary<string, ParseTextResult>(),
			GameDifficulty = pGameDifficulty,
			PlayerAmount = 4,
			OriginalVersion = pGameVersion,
			Version = pGameVersion,
			Expansions = pExpansions
		};
		SetDefaultExpansions(result);
		if (Env.Configs.Contents.TryGetValue(pAdventureConfig, out var value2))
		{
			List<string> poolItems = value2.PoolItems;
			if (poolItems != null && poolItems.Count > 0)
			{
				value2.PoolItems.ForEach(delegate(string item)
				{
					result.ItemPools[item] = 0;
				});
			}
		}
		CoreHelper.GetDifficultyConfig(pGameDifficulty, pAdventureConfig);
		int difficultyInt = CoreHelper.GetDifficultyInt(eGameDifficultyHandles.SMART_LOOT_SHUFFLE);
		List<bool> list = Enumerable.Repeat(element: false, Math.Max(1, difficultyInt)).ToList();
		list[list.Count - 1] = difficultyInt > 0;
		result.SmartLootShuffle = new ShuffleBag<bool>(list);
		result.AdventureState = AdventureState.Create(pAdventureConfig);
		return result;
	}

	public void SetEntities(List<Entity> pEntities)
	{
		_entities = pEntities;
	}

	public static void SetDefaultExpansions(GameRunData pGameRunData)
	{
		if (pGameRunData.Expansions == null)
		{
			pGameRunData.Expansions = new List<eExpansions>();
		}
		if (!pGameRunData.Expansions.Contains(eExpansions.BASE))
		{
			pGameRunData.Expansions.Add(eExpansions.BASE);
		}
		if (pGameRunData.Expansions.Contains(eExpansions.PRIMORDIAL))
		{
			return;
		}
		if (PublishPlatformHelper.Platform.PlatformId == ePlatformIds.STEAM)
		{
			if (StatsHelper.GetEnabledExpansions().Contains(eExpansions.PRIMORDIAL))
			{
				pGameRunData.Expansions.Add(eExpansions.PRIMORDIAL);
			}
		}
		else
		{
			pGameRunData.Expansions.Add(eExpansions.PRIMORDIAL);
		}
	}
}
